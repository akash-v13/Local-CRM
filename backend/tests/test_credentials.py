"""Credentials: static auth, generated tokens (OAuth2 + custom), caching and refresh."""

import base64
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Credential
from tests.conftest import FakeApis
from tests.connector_helpers import SHOP_ORDER, create_connector, create_credential
from tests.test_cases_api import create_case

OAUTH: dict[str, Any] = {
    "name": "Shop OAuth",
    "kind": "oauth2_client_credentials",
    "config": {"token_url": "https://auth.example.com/oauth/token", "scope": "orders:read"},
    "secrets": {"client_id": "my-client", "client_secret": "my-client-secret"},
}


class TokenApi:
    """A fake API protected by short-lived tokens from a token endpoint."""

    def __init__(self) -> None:
        self.issued = 0
        self.valid: set[str] = set()
        self.token_requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/oauth/token", "/login"):
            self.token_requests.append(request)
            self.issued += 1
            token = f"token-{self.issued}"
            self.valid = {token}  # issuing a new token revokes the old one
            if request.url.path == "/login":
                return httpx.Response(200, json={"data": {"token": token}})
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        auth = request.headers.get("Authorization", "")
        if auth.removeprefix("Bearer ").removeprefix("Token ") not in self.valid:
            return httpx.Response(401, json={"error": "invalid token"})
        return httpx.Response(200, json=SHOP_ORDER)


def check_token(client: TestClient, tenant_id: str, credential_id: str) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/credentials/{credential_id}/test")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def run_connector_test(client: TestClient, tenant_id: str, credential_id: str) -> dict[str, Any]:
    case = create_case(client, tenant_id)
    connector = create_connector(
        client, tenant_id, key=f"c{case['case_number'] % 10**6}", credential_id=credential_id
    )
    draft = {k: v for k, v in connector.items() if k not in ("id", "created_at", "updated_at")}
    response = client.post(
        f"/tenants/{tenant_id}/connectors/test",
        json={"case_number": case["case_number"], "draft": draft},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# ----- management ---------------------------------------------------------------------------


def test_secrets_are_never_returned(client: TestClient, tenant_id: str) -> None:
    created = create_credential(client, tenant_id, **OAUTH)
    assert created["secret_fields"] == ["client_id", "client_secret"]
    assert created["token"] == {"cached": False, "expires_at": None, "fetched_at": None}
    listing = client.get(f"/tenants/{tenant_id}/credentials").text
    assert "my-client-secret" not in listing and "secrets_ciphertext" not in listing


def test_secrets_are_encrypted_at_rest(
    client: TestClient, tenant_id: str, session_factory: sessionmaker[Session]
) -> None:
    create_credential(client, tenant_id, **OAUTH)
    with session_factory() as session:
        stored = session.scalars(select(Credential)).one()
        assert stored.secrets_ciphertext and "my-client-secret" not in stored.secrets_ciphertext


@pytest.mark.parametrize(
    "body",
    [
        {**OAUTH, "secrets": {"client_id": "x"}},  # missing client_secret
        {**OAUTH, "config": {}},  # missing token_url
        {
            "name": "K",
            "kind": "api_key",
            "config": {"header_name": "Bad Header"},
            "secrets": {"key": "k"},
        },
        {
            "name": "T",
            "kind": "token_request",
            "config": {"url": "https://a.example.com/{{case.x}}"},
        },
        {
            "name": "T",
            "kind": "token_request",
            "config": {
                "url": "https://a.example.com/login",
                "body_template": '{"u": {{secret.u}}}',
            },
        },
    ],
)
def test_invalid_credentials_are_rejected(
    client: TestClient, tenant_id: str, body: dict[str, Any]
) -> None:
    assert client.post(f"/tenants/{tenant_id}/credentials", json=body).status_code == 422


def test_replace_keeps_secrets_unless_sent_and_drops_cached_token(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = TokenApi()
    created = create_credential(client, tenant_id, **OAUTH)
    assert check_token(client, tenant_id, created["id"])["ok"] is True

    url = f"/tenants/{tenant_id}/credentials/{created['id']}"
    updated = client.put(url, json={**OAUTH, "name": "Renamed", "secrets": None}).json()
    assert updated["name"] == "Renamed"
    assert updated["secret_fields"] == ["client_id", "client_secret"]
    assert updated["token"]["cached"] is False  # settings changed → token dropped

    duplicate = client.post(f"/tenants/{tenant_id}/credentials", json={**OAUTH, "name": "Renamed"})
    assert duplicate.status_code == 409


# ----- OAuth 2.0 client credentials ---------------------------------------------------------


def test_oauth_token_request_is_standard(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    api = TokenApi()
    fake_apis.handler = api
    created = create_credential(client, tenant_id, **OAUTH)
    result = check_token(client, tenant_id, created["id"])
    assert result["ok"] is True
    assert result["token_preview"].startswith("token-")
    assert result["expires_at"] is not None

    sent = api.token_requests[-1]
    assert sent.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(sent.content.decode()) == {
        "grant_type": ["client_credentials"],
        "scope": ["orders:read"],
        "client_id": ["my-client"],
        "client_secret": ["my-client-secret"],
    }


def test_oauth_client_auth_in_basic_header(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    api = TokenApi()
    fake_apis.handler = api
    config = {**OAUTH["config"], "client_auth": "basic_header"}
    created = create_credential(client, tenant_id, **{**OAUTH, "config": config})
    check_token(client, tenant_id, created["id"])
    sent = api.token_requests[-1]
    assert (
        sent.headers["Authorization"]
        == "Basic " + base64.b64encode(b"my-client:my-client-secret").decode()
    )
    assert "client_secret" not in sent.content.decode()


def test_token_is_cached_and_shared(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    api = TokenApi()
    fake_apis.handler = api
    credential = create_credential(client, tenant_id, **OAUTH)
    first = run_connector_test(client, tenant_id, credential["id"])
    second = run_connector_test(client, tenant_id, credential["id"])
    assert first["status"] == second["status"] == "ok"
    assert first["request"]["headers"]["Authorization"] == "••••"  # token masked
    assert api.issued == 1  # one token served both calls


def test_expired_token_is_refreshed(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, session_factory: sessionmaker[Session]
) -> None:
    api = TokenApi()
    fake_apis.handler = api
    credential = create_credential(client, tenant_id, **OAUTH)
    run_connector_test(client, tenant_id, credential["id"])
    with session_factory() as session:  # pretend an hour has passed
        stored = session.scalars(select(Credential)).one()
        assert stored.token_fetched_at is not None
        stored.token_expires_at = stored.token_fetched_at
        session.commit()

    assert run_connector_test(client, tenant_id, credential["id"])["status"] == "ok"
    assert api.issued == 2


def test_rejected_token_is_refreshed_once_and_retried(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    api = TokenApi()
    fake_apis.handler = api
    credential = create_credential(client, tenant_id, **OAUTH)
    run_connector_test(client, tenant_id, credential["id"])
    api.valid = set()  # the API revokes all tokens (cache still thinks it's valid)

    result = run_connector_test(client, tenant_id, credential["id"])
    assert result["status"] == "ok"
    assert api.issued == 2


def test_token_api_failure_is_reported(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = lambda r: httpx.Response(400, json={"error": "invalid_client"})
    credential = create_credential(client, tenant_id, **OAUTH)
    result = check_token(client, tenant_id, credential["id"])
    assert result == {
        "ok": False,
        "error": "The token API returned HTTP 400.",
        "token_preview": None,
        "expires_at": None,
    }
    stored = client.get(f"/tenants/{tenant_id}/credentials/{credential['id']}").json()
    assert stored["last_error"] == "The token API returned HTTP 400."

    run = run_connector_test(client, tenant_id, credential["id"])
    assert run["status"] == "failed"
    assert run["error"].startswith("Authentication failed:")


def test_token_url_is_ssrf_checked(client: TestClient, tenant_id: str) -> None:
    from app.api.connectors import get_resolver
    from app.main import app

    app.dependency_overrides[get_resolver] = lambda: lambda host, port: ["127.0.0.1"]
    credential = create_credential(client, tenant_id, **OAUTH)
    result = check_token(client, tenant_id, credential["id"])
    assert result["ok"] is False and "not allowed" in result["error"]


# ----- custom token request -----------------------------------------------------------------


def test_custom_token_request(client: TestClient, tenant_id: str, fake_apis: FakeApis) -> None:
    api = TokenApi()
    fake_apis.handler = api
    credential = create_credential(
        client,
        tenant_id,
        name="Legacy login",
        kind="token_request",
        config={
            "method": "POST",
            "url": "https://legacy.example.com/login",
            "body_format": "json",
            "body_template": '{"user": "{{secret.username}}", "pass": "{{secret.password}}"}',
            "token_path": "data.token",
            "expires_in_path": None,
            "default_ttl_seconds": 900,
            "header_name": "Authorization",
            "header_prefix": "Token ",
        },
        secrets={"username": "svc-user", "password": 'p"w'},
    )
    result = run_connector_test(client, tenant_id, credential["id"])
    assert result["status"] == "ok", result
    login = api.token_requests[-1]
    assert json.loads(login.content) == {"user": "svc-user", "pass": 'p"w'}  # safely escaped

    status = client.get(f"/tenants/{tenant_id}/credentials/{credential['id']}").json()["token"]
    assert status["cached"] is True


def test_custom_token_request_with_missing_secret_value(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = TokenApi()
    credential = create_credential(
        client,
        tenant_id,
        name="Needs a value",
        kind="token_request",
        config={"url": "https://legacy.example.com/login?u={{secret.username}}", "method": "GET"},
        secrets={},
    )
    result = check_token(client, tenant_id, credential["id"])
    assert result["ok"] is False
    assert "secret.username" in result["error"]


# ----- static kinds -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "config", "secrets", "header", "value"),
    [
        ("api_key", {"header_name": "X-Key"}, {"key": "k1"}, "X-Key", "k1"),
        ("bearer", {}, {"token": "t1"}, "Authorization", "Bearer t1"),
        (
            "basic",
            {},
            {"username": "u", "password": "p"},
            "Authorization",
            "Basic " + base64.b64encode(b"u:p").decode(),
        ),
    ],
)
def test_static_credentials_set_the_right_header(
    client: TestClient,
    tenant_id: str,
    fake_apis: FakeApis,
    kind: str,
    config: dict[str, str],
    secrets: dict[str, str],
    header: str,
    value: str,
) -> None:
    fake_apis.handler = lambda r: httpx.Response(200, json=SHOP_ORDER)
    credential = create_credential(
        client, tenant_id, name=kind, kind=kind, config=config, secrets=secrets
    )
    assert check_token(client, tenant_id, credential["id"])["ok"] is True
    run_connector_test(client, tenant_id, credential["id"])
    assert fake_apis.requests[-1].headers[header] == value
