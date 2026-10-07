"""Turning a saved credential into request headers, including generated tokens.

Static kinds (api_key, bearer, basic) just become a header.

Token kinds (oauth2_client_credentials, token_request, and shopify with a client
id + secret) call a "generate token" API first. The token is:
- cached on the credential row, **encrypted**, with its expiry time, so every
  connector and every worker shares one token instead of requesting a new one
  per call;
- reused until shortly before it expires (EXPIRY_MARGIN), then refreshed;
- refreshed immediately if an API rejects it with 401 (see the runner).

While refreshing, the credential row is locked (SELECT ... FOR UPDATE), so two
workers needing a new token at the same moment don't both request one: the
second waits, then finds the fresh token in the cache.
"""

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.runner_settings import RunSettings
from app.domain.jsonpath import extract
from app.domain.routing import to_number
from app.domain.templates import MissingTemplateValue, render
from app.models import Credential
from app.models.base import utcnow
from app.security.secrets import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.security.ssrf import UnsafeUrlError, check_url
from app.shopify.client import shop_base_url

TOKEN_KINDS = {"oauth2_client_credentials", "token_request", "shopify"}
SHOPIFY_HEADER = "X-Shopify-Access-Token"
# Refresh this long before the token's stated expiry, so a call never starts
# with a token that dies mid-flight. Short-lived tokens use 10% of their lifetime.
EXPIRY_MARGIN = timedelta(seconds=60)
TOKEN_TIMEOUT_SECONDS = 10.0


class CredentialError(Exception):
    """The credential couldn't produce auth headers (bad secret, token API failed, ...)."""


@dataclass
class AppliedAuth:
    headers: dict[str, str]
    secret_header_names: set[str] = field(default_factory=set)
    refreshable: bool = False  # True for generated tokens: retry once with a new one on 401


@dataclass
class FetchedToken:
    token: str
    expires_at: datetime


def as_utc(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def load_secrets(credential: Credential) -> dict[str, str]:
    if not credential.secrets_ciphertext:
        return {}
    try:
        values: dict[str, str] = json.loads(decrypt_secret(credential.secrets_ciphertext))
    except SecretDecryptionError as exc:
        raise CredentialError(str(exc)) from exc
    return values


def store_secrets(credential: Credential, values: dict[str, str]) -> None:
    credential.secrets_ciphertext = encrypt_secret(json.dumps(values))


def _token_is_fresh(credential: Credential, now: datetime) -> bool:
    if not credential.token_ciphertext or credential.token_expires_at is None:
        return False
    expires = as_utc(credential.token_expires_at)
    fetched = as_utc(credential.token_fetched_at or now)
    margin = min(EXPIRY_MARGIN, (expires - fetched) * 0.1)
    return expires - margin > now


def fetch_token(
    credential: Credential, secrets: dict[str, str], client: httpx.Client, settings: RunSettings
) -> FetchedToken:
    """Call the credential's token API. Raises CredentialError with a readable reason."""
    config = credential.config
    headers = {"Accept": "application/json"}
    body: str | None
    token_path: str
    expires_path: str | None
    default_ttl: int
    if credential.kind == "oauth2_client_credentials":
        method, url = "POST", config["token_url"]
        form: dict[str, str] = {"grant_type": "client_credentials"}
        if config.get("scope"):
            form["scope"] = config["scope"]
        if config.get("audience"):
            form["audience"] = config["audience"]
        if config.get("client_auth") == "basic_header":
            pair = f"{secrets['client_id']}:{secrets['client_secret']}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form["client_id"] = secrets["client_id"]
            form["client_secret"] = secrets["client_secret"]
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(form)
        token_path, expires_path, default_ttl = "access_token", "expires_in", 3600
    elif credential.kind == "shopify":
        # Shopify's client credentials grant: a 24-hour token for the app's own store.
        method = "POST"
        url = shop_base_url(config["shop"], settings.shopify_api_base) + "/admin/oauth/access_token"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": secrets.get("client_id", ""),
                "client_secret": secrets.get("client_secret", ""),
            }
        )
        token_path, expires_path, default_ttl = "access_token", "expires_in", 86_399
    else:
        context = {"secret": secrets}
        try:
            method = config["method"]
            url = render(config["url"], context, "url")
            headers.update({k: render(v, context, "header") for k, v in config["headers"].items()})
            template = config.get("body_template")
            if template and config["body_format"] == "form":
                body = render(template, context, "url")
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif template:
                body = render(template, context, "json")
                headers.setdefault("Content-Type", "application/json")
            else:
                body = None
        except MissingTemplateValue as exc:
            raise CredentialError(f"No secret value for {{{{{exc.path}}}}}.") from exc
        token_path = config["token_path"]
        expires_path = config.get("expires_in_path")
        default_ttl = config["default_ttl_seconds"]

    try:
        check_url(
            url,
            allow_http=settings.allow_http,
            allowed_hosts=settings.allowed_hosts,
            resolve=settings.resolve,
        )
    except UnsafeUrlError as exc:
        raise CredentialError(f"Token URL not allowed: {exc}") from exc

    try:
        response = client.request(
            method,
            url,
            headers=headers,
            content=body,
            timeout=TOKEN_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        raise CredentialError("The token API didn't respond in time.") from exc
    except httpx.TransportError as exc:
        raise CredentialError(f"Couldn't reach the token API: {exc.__class__.__name__}.") from exc

    if not 200 <= response.status_code < 300:
        raise CredentialError(f"The token API returned HTTP {response.status_code}.")
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise CredentialError("The token API's response isn't JSON.") from exc

    found, token = extract(payload, token_path)
    if not found or not isinstance(token, str) or not token:
        raise CredentialError(f"No token at '{token_path}' in the token API's response.")
    ttl = default_ttl
    if expires_path:
        found, raw = extract(payload, expires_path)
        seconds = to_number(raw) if found else None
        if seconds is not None and seconds > 0:
            ttl = int(seconds)
    return FetchedToken(token=token, expires_at=utcnow() + timedelta(seconds=ttl))


class AuthProvider:
    """Produces auth headers for credentials, caching generated tokens in the database."""

    def __init__(
        self, session_factory: sessionmaker[Session], client: httpx.Client, settings: RunSettings
    ) -> None:
        self.session_factory = session_factory
        self.client = client
        self.settings = settings

    def headers_for(self, credential_id: Any, *, force_refresh: bool = False) -> AppliedAuth:
        with self.session_factory() as session:
            stmt = select(Credential).where(Credential.id == credential_id)
            credential = session.scalars(stmt.with_for_update()).one_or_none()
            if credential is None:
                raise CredentialError("The connector's credential no longer exists.")
            secrets = load_secrets(credential)

            if credential.kind not in TOKEN_KINDS or (
                credential.kind == "shopify" and secrets.get("access_token")
            ):
                return self._static(credential, secrets)

            now = utcnow()
            if not force_refresh and _token_is_fresh(credential, now):
                assert credential.token_ciphertext is not None
                token = decrypt_secret(credential.token_ciphertext)
            else:
                try:
                    fetched = fetch_token(credential, secrets, self.client, self.settings)
                except CredentialError as exc:
                    credential.last_error = str(exc)
                    session.commit()
                    raise
                token = fetched.token
                credential.token_ciphertext = encrypt_secret(token)
                credential.token_expires_at = fetched.expires_at
                credential.token_fetched_at = now
                credential.last_error = None
                session.commit()  # also releases the row lock

            if credential.kind == "token_request":
                name = credential.config["header_name"]
                value = credential.config["header_prefix"] + token
            elif credential.kind == "shopify":
                name, value = SHOPIFY_HEADER, token
            else:
                name, value = "Authorization", f"Bearer {token}"
            return AppliedAuth({name: value}, {name}, refreshable=True)

    @staticmethod
    def _static(credential: Credential, secrets: dict[str, str]) -> AppliedAuth:
        try:
            if credential.kind == "api_key":
                name, value = credential.config["header_name"], secrets["key"]
            elif credential.kind == "bearer":
                name, value = "Authorization", f"Bearer {secrets['token']}"
            elif credential.kind == "shopify":
                name, value = SHOPIFY_HEADER, secrets["access_token"]
            else:
                pair = f"{secrets['username']}:{secrets['password']}"
                name = "Authorization"
                value = "Basic " + base64.b64encode(pair.encode()).decode()
        except KeyError as exc:
            raise CredentialError(f"The credential is missing its secret '{exc.args[0]}'.") from exc
        return AppliedAuth({name: value}, {name})
