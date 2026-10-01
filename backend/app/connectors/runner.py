"""Run one connector against one case.

Steps, each of which can end the run early with a clear reason:

1. `run_when`: skip if the case doesn't match the connector's criteria.
2. Build the request from templates (skip if the case lacks a value, e.g. no
   order number).
3. SSRF check on the final URL (app/security/ssrf.py).
4. Call the API: no redirects followed, response size capped, retries with a
   short backoff on network errors, timeouts, 429 and 5xx (not on other 4xx:
   retrying a 404 won't help).
5. Parse JSON and pick out the mapped fields.

Nothing here touches the database, so it's easy to test with a fake HTTP
transport, and the caller decides what to do with the outcome.
"""

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.domain.jsonpath import extract
from app.domain.routing import evaluate_criteria
from app.domain.templates import MissingTemplateValue, render
from app.schemas import ConnectorConfig, ConnectorTestResult, RequestPreview
from app.security.ssrf import Resolver, UnsafeUrlError, check_url

MASK = "••••"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RunSettings:
    allow_http: bool
    allowed_hosts: list[str]
    max_response_bytes: int
    resolve: Resolver
    sleep: Callable[[float], None] = time.sleep


@dataclass
class _Request:
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    secret_headers: set[str] = field(default_factory=set)

    def preview(self) -> RequestPreview:
        return RequestPreview(
            method=self.method,
            url=self.url,
            headers={k: MASK if k in self.secret_headers else v for k, v in self.headers.items()},
            body=self.body,
        )


def build_request(
    config: ConnectorConfig, template_context: dict[str, Any], secret: str | None
) -> _Request:
    """Render URL, headers and body; add auth. Raises MissingTemplateValue."""
    url = render(config.url_template, template_context, "url")
    headers = {k: render(v, template_context, "header") for k, v in config.headers.items()}
    body = render(config.body_template, template_context, "json") if config.body_template else None
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")

    request = _Request(config.method, url, headers, body)
    if config.auth_type != "none":
        if not secret:
            raise ValueError("This connector needs a secret (API key / token), but none is set.")
        if config.auth_type == "api_key":
            name = config.auth_header_name or "X-Api-Key"
        else:
            name = "Authorization"
        if config.auth_type == "bearer":
            value = f"Bearer {secret}"
        elif config.auth_type == "basic":
            value = "Basic " + base64.b64encode(secret.encode()).decode()
        else:
            value = secret
        request.headers[name] = value
        request.secret_headers.add(name)
    return request


def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            raise ValueError(f"Response is larger than the {limit:,}-byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def run_connector(
    config: ConnectorConfig,
    *,
    template_context: dict[str, Any],
    routing_context: dict[str, Any],
    secret: str | None,
    client: httpx.Client,
    settings: RunSettings,
) -> ConnectorTestResult:
    """Run a connector and report what happened. Never raises for expected failures."""
    if config.run_when.conditions:
        matched, _ = evaluate_criteria(config.run_when.model_dump(), routing_context)
        if not matched:
            return ConnectorTestResult(status="skipped", error="Case doesn't match 'run when'.")

    try:
        request = build_request(config, template_context, secret)
    except MissingTemplateValue as exc:
        return ConnectorTestResult(status="skipped", error=f"Case has no value for {exc.path}.")
    except ValueError as exc:
        return ConnectorTestResult(status="failed", error=str(exc))

    preview = request.preview()
    try:
        check_url(
            request.url,
            allow_http=settings.allow_http,
            allowed_hosts=settings.allowed_hosts,
            resolve=settings.resolve,
        )
    except UnsafeUrlError as exc:
        return ConnectorTestResult(status="failed", error=str(exc), request=preview)

    started = time.monotonic()
    attempts = config.max_retries + 1
    status_code: int | None = None
    content = b""
    content_type = ""
    error: str | None = None
    for attempt in range(1, attempts + 1):
        error = None
        try:
            with client.stream(
                request.method,
                request.url,
                headers=request.headers,
                content=request.body,
                timeout=config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                status_code = response.status_code
                content_type = response.headers.get("content-type", "")
                content = _read_limited(response, settings.max_response_bytes)
            if status_code in RETRYABLE_STATUS:
                error = f"The API returned HTTP {status_code}."
            else:
                break
        except httpx.TimeoutException:
            error = f"The API didn't respond within {config.timeout_seconds:g}s."
        except httpx.TransportError as exc:
            error = f"Couldn't connect: {exc.__class__.__name__}."
        except ValueError as exc:  # response too large
            error = str(exc)
            break
        if attempt < attempts:
            settings.sleep(0.5 * attempt)

    duration_ms = int((time.monotonic() - started) * 1000)
    base: dict[str, Any] = {
        "request": preview,
        "http_status": status_code,
        "duration_ms": duration_ms,
    }

    if error:
        return ConnectorTestResult(status="failed", error=error, **base)
    assert status_code is not None
    if 300 <= status_code < 400:
        return ConnectorTestResult(
            status="failed",
            error=f"HTTP {status_code} redirect (redirects aren't followed).",
            **base,
        )
    text = content.decode("utf-8", errors="replace")
    if not 200 <= status_code < 300:
        return ConnectorTestResult(
            status="failed",
            error=f"The API returned HTTP {status_code}.",
            response_text=text[:2000],
            **base,
        )
    try:
        payload = json.loads(text)
    except ValueError:
        return ConnectorTestResult(
            status="failed",
            error=f"The response isn't JSON (content type: {content_type or 'unknown'}).",
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
