"""Run one connector against one case.

Steps, each of which can end the run early with a clear reason:

1. `run_when`: skip if the case doesn't match the connector's criteria.
2. Build the request from templates (skip if the case lacks a value, e.g. no
   order number).
3. SSRF check on the final URL (app/security/ssrf.py).
4. Authenticate via the connector's credential (app/connectors/auth.py).
5. Send: no redirects followed, response size capped, retries with a short
   backoff on network errors, timeouts, 429 and 5xx (not other 4xx: retrying
   a 404 won't help). If a *generated token* is rejected with 401, get a fresh
   token once and send again.
6. Parse JSON and pick out the mapped fields.

Nothing here touches the database directly (token caching goes through the
`auth` callable), so it's easy to test with a fake HTTP transport.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.connectors.auth import AppliedAuth, CredentialError
from app.connectors.runner_settings import RunSettings
from app.domain.jsonpath import extract
from app.domain.routing import evaluate_criteria
from app.domain.templates import MissingTemplateValue, render
from app.schemas import ConnectorConfig, ConnectorTestResult, RequestPreview
from app.security.ssrf import UnsafeUrlError, check_url

__all__ = ["AuthSource", "RunSettings", "build_request", "run_connector"]

MASK = "••••"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Returns auth headers; called with True to force a brand-new token after a 401.
AuthSource = Callable[[bool], AppliedAuth]


@dataclass
class _Request:
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    secret_headers: set[str] = field(default_factory=set)

    def with_auth(self, auth: AppliedAuth) -> "_Request":
        return _Request(
            self.method,
            self.url,
            {**self.headers, **auth.headers},
            self.body,
            self.secret_headers | auth.secret_header_names,
        )

    def preview(self) -> RequestPreview:
        return RequestPreview(
            method=self.method,
            url=self.url,
            headers={k: MASK if k in self.secret_headers else v for k, v in self.headers.items()},
            body=self.body,
        )


@dataclass
class _Sent:
    status_code: int | None = None
    content: bytes = b""
    content_type: str = ""
    error: str | None = None


def build_request(config: ConnectorConfig, template_context: dict[str, Any]) -> _Request:
    """Render URL, headers and body. Raises MissingTemplateValue."""
    url = render(config.url_template, template_context, "url")
    headers = {k: render(v, template_context, "header") for k, v in config.headers.items()}
    body = render(config.body_template, template_context, "json") if config.body_template else None
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    return _Request(config.method, url, headers, body)


def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            raise ValueError(f"Response is larger than the {limit:,}-byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _send(
    request: _Request, config: ConnectorConfig, client: httpx.Client, settings: RunSettings
) -> _Sent:
    """Send with retries on transient failures. Never raises for network problems."""
    attempts = config.max_retries + 1
    sent = _Sent()
    for attempt in range(1, attempts + 1):
        sent = _Sent()
        try:
            with client.stream(
                request.method,
                request.url,
                headers=request.headers,
                content=request.body,
                timeout=config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                sent.status_code = response.status_code
                sent.content_type = response.headers.get("content-type", "")
                sent.content = _read_limited(response, settings.max_response_bytes)
            if sent.status_code not in RETRYABLE_STATUS:
                return sent
            sent.error = f"The API returned HTTP {sent.status_code}."
        except httpx.TimeoutException:
            sent.error = f"The API didn't respond within {config.timeout_seconds:g}s."
        except httpx.TransportError as exc:
            sent.error = f"Couldn't connect: {exc.__class__.__name__}."
        except ValueError as exc:  # response too large: retrying won't help
            sent.error = str(exc)
            return sent
        if attempt < attempts:
            settings.sleep(0.5 * attempt)
    return sent


def run_connector(
    config: ConnectorConfig,
    *,
    template_context: dict[str, Any],
    routing_context: dict[str, Any],
    auth: AuthSource | None,
    client: httpx.Client,
    settings: RunSettings,
) -> ConnectorTestResult:
    """Run a connector and report what happened. Never raises for expected failures."""
    if config.run_when.conditions:
        matched, _ = evaluate_criteria(config.run_when.model_dump(), routing_context)
        if not matched:
            return ConnectorTestResult(status="skipped", error="Case doesn't match 'run when'.")

    try:
        request = build_request(config, template_context)
    except MissingTemplateValue as exc:
        return ConnectorTestResult(status="skipped", error=f"Case has no value for {exc.path}.")

    try:
        check_url(
            request.url,
            allow_http=settings.allow_http,
            allowed_hosts=settings.allowed_hosts,
            resolve=settings.resolve,
        )
    except UnsafeUrlError as exc:
        return ConnectorTestResult(status="failed", error=str(exc), request=request.preview())

    unauthenticated = request
    applied: AppliedAuth | None = None
    if auth is not None:
        try:
            applied = auth(False)
        except CredentialError as exc:
            return ConnectorTestResult(
                status="failed", error=f"Authentication failed: {exc}", request=request.preview()
            )
        request = unauthenticated.with_auth(applied)

    started = time.monotonic()
    sent = _send(request, config, client, settings)
    if sent.status_code == 401 and applied is not None and applied.refreshable and auth:
        # The cached token was rejected (revoked, or expired early): get a new one, once.
        try:
            applied = auth(True)
        except CredentialError as exc:
            return ConnectorTestResult(
                status="failed", error=f"Authentication failed: {exc}", request=request.preview()
            )
        request = unauthenticated.with_auth(applied)
        sent = _send(request, config, client, settings)

    base: dict[str, Any] = {
        "request": request.preview(),
        "http_status": sent.status_code,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if sent.error:
        return ConnectorTestResult(status="failed", error=sent.error, **base)
    status = sent.status_code
    assert status is not None
    text = sent.content.decode("utf-8", errors="replace")
    if 300 <= status < 400:
        return ConnectorTestResult(
            status="failed", error=f"HTTP {status} redirect (redirects aren't followed).", **base
        )
    if not 200 <= status < 300:
        return ConnectorTestResult(
            status="failed",
            error=f"The API returned HTTP {status}.",
            response_text=text[:2000],
            **base,
        )
    try:
        payload = json.loads(text)
    except ValueError:
        return ConnectorTestResult(
            status="failed",
            error=f"The response isn't JSON (content type: {sent.content_type or 'unknown'}).",
            response_text=text[:2000],
            **base,
        )

    data: dict[str, Any] = {}
    missing: list[str] = []
    for mapping in config.field_mappings:
        found, value = extract(payload, mapping.path)
        if found:
            data[mapping.target] = value
        else:
            missing.append(mapping.target)
    return ConnectorTestResult(
        status="ok", data=data, missing=missing, response_json=payload, **base
    )
