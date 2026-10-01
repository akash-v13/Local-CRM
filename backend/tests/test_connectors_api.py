"""Connector management API and the live connector test."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.connectors import get_resolver
from app.main import app
from tests.conftest import FakeApis
from tests.connector_helpers import SHOP_CONNECTOR, create_connector, shop_api
from tests.test_cases_api import create_case


def test_secret_is_write_only(client: TestClient, tenant_id: str) -> None:
    connector = create_connector(client, tenant_id)
    assert connector["has_secret"] is True
    assert "secret" not in connector and "secret_ciphertext" not in connector
    assert "super-secret-key" not in client.get(f"/tenants/{tenant_id}/connectors").text


def test_replace_keeps_or_clears_the_secret(client: TestClient, tenant_id: str) -> None:
    connector = create_connector(client, tenant_id)
    url = f"/tenants/{tenant_id}/connectors/{connector['id']}"
    without_secret = {k: v for k, v in SHOP_CONNECTOR.items() if k != "secret"}

    kept = client.put(url, json={**without_secret, "name": "Renamed"}).json()
    assert (kept["name"], kept["has_secret"]) == ("Renamed", True)

    cleared = client.put(url, json={**without_secret, "clear_secret": True}).json()
    assert cleared["has_secret"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": "Shop"},  # keys are lowercase identifiers
        {"auth_type": "api_key", "auth_header_name": None},  # api key needs a header name
        {"method": "GET", "body_template": '{"a": "b"}'},  # body only with POST
        {"method": "POST", "body_template": '{"a": {{case.attributes.x}}}'},  # unquoted placeholder
        {"url_template": "https://x.example.com/{{customer.email}}"},  # unknown placeholder root
        {"url_template": "ftp://x.example.com/"},
        {"headers": {"Bad Header": "x"}},
        {"field_mappings": [{"path": "a", "target": "x"}, {"path": "b", "target": "x"}]},
        {"timeout_seconds": 60},
    ],
)
def test_invalid_configuration_is_rejected(
    client: TestClient, tenant_id: str, overrides: dict[str, Any]
) -> None:
    response = client.post(f"/tenants/{tenant_id}/connectors", json={**SHOP_CONNECTOR, **overrides})
    assert response.status_code == 422, overrides


def test_duplicate_key_is_a_conflict(client: TestClient, tenant_id: str) -> None:
    create_connector(client, tenant_id)
    response = client.post(f"/tenants/{tenant_id}/connectors", json=SHOP_CONNECTOR)
    assert response.status_code == 409
    assert "already uses the key 'shop'" in response.json()["detail"]


def test_connectors_are_tenant_scoped(client: TestClient, tenant_id: str) -> None:
    connector = create_connector(client, tenant_id)
    other = client.post("/tenants", json={"name": "Other"}).json()["id"]
    assert client.get(f"/tenants/{other}/connectors/{connector['id']}").status_code == 404
    assert client.get(f"/tenants/{other}/connectors").json() == []


# ----- live test ---------------------------------------------------------------------------


def run_test(client: TestClient, tenant_id: str, case_number: int, **draft: Any) -> dict[str, Any]:
    body = {"case_number": case_number, "draft": {**SHOP_CONNECTOR, **draft}}
    response = client.post(f"/tenants/{tenant_id}/connectors/test", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_live_test_returns_response_and_mapped_fields(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = shop_api
    case = create_case(client, tenant_id)  # attributes.orderNumber = ORD-55012

    result = run_test(client, tenant_id, case["case_number"])
    assert result["status"] == "ok", result
    assert result["data"] == {
        "orderTotal": 742.5,
        "carrier": "FastShip",
        "trackingNumber": "TRK123",
        "daysLate": 6,
    }
    assert result["response_json"]["items"] == [{"sku": "A1"}]  # full response, for field picking
    assert result["request"]["url"] == "https://shop.example.com/orders/ORD-55012"
    assert result["request"]["headers"]["X-Api-Key"] == "••••"  # secret masked
    assert fake_apis.requests[-1].headers["X-Api-Key"] == "super-secret-key"  # but really sent


def test_live_test_reuses_the_stored_secret(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = shop_api
    saved = create_connector(client, tenant_id)
    case = create_case(client, tenant_id)
    body = {
        "case_number": case["case_number"],
        "draft": {k: v for k, v in SHOP_CONNECTOR.items() if k != "secret"},
        "connector_id": saved["id"],
    }
    result = client.post(f"/tenants/{tenant_id}/connectors/test", json=body).json()
    assert result["status"] == "ok", result


def test_live_test_reports_missing_mapped_fields(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    fake_apis.handler = shop_api
    case = create_case(client, tenant_id)
    mappings = [{"path": "carrier", "target": "carrier"}, {"path": "nope.x", "target": "ghost"}]
    result = run_test(client, tenant_id, case["case_number"], field_mappings=mappings)
    assert (result["data"], result["missing"]) == ({"carrier": "FastShip"}, ["ghost"])


@pytest.mark.parametrize(
    ("handler", "expected_error"),
    [
        (lambda r: httpx.Response(404, json={}), "HTTP 404"),
        (lambda r: httpx.Response(302, headers={"Location": "http://10.0.0.1/"}), "redirect"),
        (lambda r: httpx.Response(200, text="<html>hi</html>"), "isn't JSON"),
        (lambda r: httpx.Response(503), "HTTP 503"),
    ],
)
def test_live_test_failures_are_explained(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, handler: Any, expected_error: str
) -> None:
    fake_apis.handler = handler
    case = create_case(client, tenant_id)
    result = run_test(client, tenant_id, case["case_number"])
    assert result["status"] == "failed"
    assert expected_error in result["error"]


def test_timeouts_are_retried_then_reported(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.connectors.runner.time.sleep", lambda s: None)  # no real waiting
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    fake_apis.handler = timeout
    case = create_case(client, tenant_id)
    result = run_test(client, tenant_id, case["case_number"], max_retries=2)
    assert result["status"] == "failed"
    assert "didn't respond" in result["error"]
    assert len(fake_apis.requests) == 3  # 1 try + 2 retries


def test_missing_case_data_skips_the_call(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    case = client.post(
        f"/tenants/{tenant_id}/cases",
        json={"channel": "webform", "customer": {"email": "x@example.com"}, "message": "hi"},
    ).json()  # no order number
    result = run_test(client, tenant_id, case["case_number"])
    assert result["status"] == "skipped"
    assert "case.attributes.orderNumber" in result["error"]
    assert fake_apis.requests == []


def test_private_addresses_are_blocked(
    client: TestClient, tenant_id: str, fake_apis: FakeApis
) -> None:
    app.dependency_overrides[get_resolver] = lambda: (lambda host, port: ["169.254.169.254"])
    case = create_case(client, tenant_id)
    result = run_test(client, tenant_id, case["case_number"])
    assert result["status"] == "failed"
    assert "private or reserved" in result["error"]
    assert fake_apis.requests == []  # never called


def test_oversized_responses_are_refused(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "connector_max_response_bytes", 100)
    fake_apis.handler = lambda r: httpx.Response(200, json={"blob": "x" * 500})
    case = create_case(client, tenant_id)
    result = run_test(client, tenant_id, case["case_number"])
    assert result["status"] == "failed"
    assert "larger than" in result["error"]
