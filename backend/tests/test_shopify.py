"""Shopify: connecting a store, order lookup at intake, and issuing compensation.

The fake Shopify is the demo mock (mocks/shopify.py) behind httpx's MockTransport,
with failures injected around it: dropped connections, throttling, and requests
Shopify carried out but answered with an error (the dangerous case for money).
"""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import mocks.shopify as mock
from app.config import Settings, get_settings
from app.main import app
from app.models import Job
from app.services.enrichment import EnrichmentService
from app.shopify.orders import order_fields, order_search, same_order_name
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver
from tests.test_cases_api import CASE_PAYLOAD

SHOP = "harbor-goods.myshopify.com"
BASE = "https://shopify.test/shopify"
EMAIL = CASE_PAYLOAD["customer"]["email"]
ORDER = CASE_PAYLOAD["attributes"]["orderNumber"]  # ORD-55012
SETTINGS = Settings(shopify_api_base=BASE)


class FakeShopify:
    """Forwards to the mock app; `fail` makes the next matching operation fail.

    fail = (operation, mode). Modes:
      "connect"   never reaches Shopify (ConnectError)
      "throttle"  Shopify answers THROTTLED (nothing done)
      "after500"  Shopify does it, then answers HTTP 500 (outcome unknown)
      "timeout"   Shopify does it, then the connection times out (outcome unknown)
    """

    def __init__(self) -> None:
        api = FastAPI()
        api.include_router(mock.router)
        self.mock = TestClient(api)
        self.fail: list[tuple[str, str]] = []
        self.operations: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        op = ""
        if request.url.path.endswith("graphql.json"):
            op = json.loads(request.content).get("operationName", "")
            self.operations.append(op)
        mode = next((m for o, m in self.fail if o == op), None)
        if mode:
            self.fail.remove((op, mode))
        if mode == "connect":
            raise httpx.ConnectError("down", request=request)
        if mode == "throttle":
            return httpx.Response(
                200,
                json={"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]},
            )
        response = self.mock.request(
            request.method,
            "http://testserver" + request.url.path,
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        if mode == "after500":
            return httpx.Response(500, text="oops")
        if mode == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": "application/json"},
        )

    @property
    def refunds(self) -> list[dict[str, Any]]:
        return [r for rs in mock._state["refunds"].values() for r in rs]


@pytest.fixture
def shopify(client: TestClient, fake_apis: FakeApis) -> Iterator[FakeShopify]:
    for value in mock._state.values():
        value.clear()
    mock._tokens.clear()
    mock._state["owners"][ORDER] = EMAIL
    fake = FakeShopify()
    fake_apis.handler = fake
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    yield fake


@pytest.fixture
def work(session_factory: sessionmaker[Session], fake_apis: FakeApis) -> Callable[[], None]:
    def run() -> None:
        with session_factory() as session:  # no waiting for retry backoff in tests
            for job in session.scalars(select(Job).where(Job.status == "pending")):
                job.run_after = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=SETTINGS, resolve=public_resolver
            )
            while run_once(service):
                pass

    return run


def connect(client: TestClient, tenant_id: str, secret: str = mock.CLIENT_SECRET) -> Any:
    response = client.post(
        f"/tenants/{tenant_id}/shopify/connect",
        json={"shop": SHOP, "client_id": mock.CLIENT_ID, "client_secret": secret},
    )
    assert response.status_code == 200, response.text
    return response.json()


def new_case(client: TestClient, tenant_id: str, **changes: Any) -> int:
    response = client.post(f"/tenants/{tenant_id}/cases", json={**CASE_PAYLOAD, **changes})
    assert response.status_code == 201, response.text
    number: int = response.json()["case_number"]
    return number


def case(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{number}").json()
    return body


# ----- pure ---------------------------------------------------------------------------------


def test_order_search_and_names() -> None:
    assert order_search("1001") == 'name:"#1001"'
    assert order_search(" NW-10211 ") == 'name:"NW-10211"'
    assert order_search('x" OR name:*') == 'name:"xORname"'  # can't widen the search
    assert order_search("") is None
    assert same_order_name("#1001", "1001") and not same_order_name("#10012", "1001")


def test_order_fields_days_late() -> None:
    order: dict[str, Any] = {
        "id": "gid://shopify/Order/1",
        "name": "#1001",
        "createdAt": "2026-09-01T10:00:00Z",
        "totalPriceSet": {"shopMoney": {"amount": "120.50", "currencyCode": "USD"}},
        "fulfillments": [
            {
                "createdAt": "2026-09-02T00:00:00Z",
                "estimatedDeliveryAt": "2026-09-05T00:00:00Z",
                "deliveredAt": None,
                "trackingInfo": [{"number": "1Z9", "company": "UPS", "url": None}],
            }
        ],
        "customer": {"id": "gid://shopify/Customer/7", "numberOfOrders": "3"},
    }
    now = datetime(2026, 9, 9, 12, tzinfo=UTC)
    fields = order_fields(order, now=now, matched_by="order number")
    assert fields["daysLate"] == 4 and fields["orderTotal"] == 120.5
    assert fields["carrier"] == "UPS" and fields["customerOrders"] == 3
    assert "trackingUrl" not in fields  # None values are left out
    order["fulfillments"][0]["deliveredAt"] = "2026-09-04T00:00:00Z"  # early
    assert order_fields(order, now=now, matched_by="x")["daysLate"] == 0


# ----- connecting -----------------------------------------------------------------------------


def test_connect_and_check(client: TestClient, tenant_id: str, shopify: FakeShopify) -> None:
    result = connect(client, tenant_id)
    assert result["ok"] and result["shop_name"] == "Harbor Goods", result
    info = client.get(f"/tenants/{tenant_id}/shopify").json()
    assert info["shop"] == SHOP and info["settings"]["enabled"]
    [credential] = client.get(f"/tenants/{tenant_id}/credentials").json()
    assert credential["kind"] == "shopify" and set(credential["secret_fields"]) == {
        "client_id",
        "client_secret",
    }
    # Reconnecting with a wrong secret updates the same credential and explains the failure.
    bad = connect(client, tenant_id, secret="wrong")
    assert not bad["ok"] and "token" in bad["detail"]
    assert len(client.get(f"/tenants/{tenant_id}/credentials").json()) == 1


def test_connectors_cant_use_the_shopify_key(client: TestClient, tenant_id: str) -> None:
    response = client.post(
        f"/tenants/{tenant_id}/connectors",
        json={"key": "shopify", "name": "x", "url_template": "https://api.example.com/x"},
    )
    assert response.status_code == 422


# ----- order lookup -------------------------------------------------------------------------


def test_lookup_at_intake(
    client: TestClient, tenant_id: str, shopify: FakeShopify, work: Callable[[], None]
) -> None:
    connect(client, tenant_id)
    number = new_case(client, tenant_id)
    assert case(client, tenant_id, number)["status"] == "Intake"
    work()
    c = case(client, tenant_id, number)
    step = c["enrichment"]["shopify"]
    assert step["status"] == "ok" and step["connectorName"] == "Shopify order"
    data = step["data"]
    assert data["orderNumber"] == ORDER and data["matchedBy"] == "order number"
    assert data["emailMatches"] is True and data["currency"] == "USD"
    assert isinstance(data["daysLate"], int) and data["carrier"]
    assert c["status"] == "Queued"  # routed after the lookup

    fields = [f["key"] for f in client.get(f"/tenants/{tenant_id}/routing/fields").json()["fields"]]
    assert "enrichment.shopify.daysLate" in fields
    pipeline = client.get(f"/tenants/{tenant_id}/pipeline").json()
    assert pipeline["shopify"]["shop"] == SHOP
    run = client.get(f"/tenants/{tenant_id}/pipeline/executions/{number}").json()
    assert run["steps"][0]["key"] == "shopify" and run["steps"][0]["position"] == 1


def test_lookup_never_guesses(client: TestClient, tenant_id: str, shopify: FakeShopify) -> None:
    connect(client, tenant_id)
    url = f"/tenants/{tenant_id}/shopify/lookup"
    missing = client.post(url, json={"order_number": "ORD-404", "email": EMAIL}).json()
    assert missing["status"] == "failed" and "No Shopify order ORD-404" in missing["error"]
    assert missing["searched"] == ['name:"ORD-404"']  # no fallback to another order
    by_email = client.post(url, json={"email": EMAIL}).json()
    assert by_email["status"] == "ok" and by_email["fields"]["matchedBy"] == "email (latest order)"
    nobody = client.post(url, json={"email": "new@example.com"}).json()
    assert nobody["status"] == "skipped"
    other = client.post(url, json={"order_number": "ORD-777", "email": EMAIL}).json()
    assert other["fields"]["emailMatches"] is False
    assert other["admin_url"].startswith(f"https://{SHOP}/admin/orders/")


# ----- issuing compensation --------------------------------------------------------------------


def pay_with_shopify(client: TestClient, tenant_id: str, outcome: dict[str, Any]) -> None:
    connect(client, tenant_id)
    client.post(
        f"/tenants/{tenant_id}/compensation/rules",
        json={"name": "Late", "priority": 1, "outcome": outcome},
    )
    response = client.put(
        f"/tenants/{tenant_id}/payouts/settings",
        json={
            "enabled": True,
            "methods": {
                "refund": "shopify_refund",
                "store_credit": "shopify_credit",
                "voucher": "shopify_discount",
            },
        },
    )
    assert response.status_code == 200, response.text


def payout(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    decision: dict[str, Any] = case(client, tenant_id, number)["decisions"]["compensation"]
    return decision


def test_refund_through_shopify(
    client: TestClient, tenant_id: str, shopify: FakeShopify, work: Callable[[], None]
) -> None:
    pay_with_shopify(client, tenant_id, {"type": "refund", "amount": 30})
    number = new_case(client, tenant_id)
    work()  # lookup → route → decide → payout job
    d = payout(client, tenant_id, number)
    assert d["payout"]["status"] == "succeeded", d
    assert d["label"] == "Refund of USD 30.00 (issued to the original payment)"
    [refund] = shopify.refunds
    assert refund["amount"] == "30.00" and str(number) in refund["note"]
    [row] = client.get(f"/tenants/{tenant_id}/cases/{number}/payouts").json()
    assert row["provider"] == "shopify" and row["details"]["order"] == ORDER


@pytest.mark.parametrize("mode", ["connect", "throttle", "after500", "timeout"])
def test_refund_retries_never_pay_twice(
    client: TestClient,
    tenant_id: str,
    shopify: FakeShopify,
    work: Callable[[], None],
    mode: str,
) -> None:
    pay_with_shopify(client, tenant_id, {"type": "refund", "amount": 30})
    shopify.fail.append(("LcrmRefund", mode))
    number = new_case(client, tenant_id)
    work()
    assert payout(client, tenant_id, number)["payout"]["status"] == "retrying"
    work()  # the retry
    assert payout(client, tenant_id, number)["payout"]["status"] == "succeeded"
    assert len(shopify.refunds) == 1


def test_refund_refused_when_the_order_is_someone_elses(
    client: TestClient, tenant_id: str, shopify: FakeShopify, work: Callable[[], None]
) -> None:
    pay_with_shopify(client, tenant_id, {"type": "refund", "amount": 30})
    number = new_case(client, tenant_id, attributes={"orderNumber": "ORD-777"})
    work()
    d = payout(client, tenant_id, number)
    assert d["payout"]["status"] == "failed" and "different email" in d["payout"]["error"]
    assert shopify.refunds == []


def test_store_credit_and_unknown_outcomes(
    client: TestClient, tenant_id: str, shopify: FakeShopify, work: Callable[[], None]
) -> None:
    pay_with_shopify(client, tenant_id, {"type": "store_credit", "amount": 12})
    number = new_case(client, tenant_id)
    work()
    d = payout(client, tenant_id, number)
    assert d["payout"]["status"] == "succeeded"
    assert d["label"] == "Store credit of USD 12.00 (added to the customer's account)"
    assert list(mock._state["credit"].values()) == [12.0]

    # No idempotency key for store credit: an unclear answer is never retried blindly.
    shopify.fail.append(("LcrmStoreCredit", "after500"))
    mock._state["owners"]["ORD-888"] = "amy@example.com"
    second = new_case(
        client,
        tenant_id,
        customer={"email": "amy@example.com", "display_name": "Amy"},
        attributes={"orderNumber": "ORD-888"},
    )
    work()
    d = payout(client, tenant_id, second)
    assert d["payout"]["status"] == "failed" and "before clicking Try again" in d["payout"]["error"]
    assert sorted(mock._state["credit"].values()) == [12.0, 12.0]  # it did go through, once


@pytest.mark.parametrize("mode", [None, "after500"])
def test_discount_code(
    client: TestClient,
    tenant_id: str,
    shopify: FakeShopify,
    work: Callable[[], None],
    mode: str | None,
) -> None:
    pay_with_shopify(client, tenant_id, {"type": "voucher", "amount": 15})
    if mode:
        shopify.fail.append(("LcrmDiscount", mode))
    number = new_case(client, tenant_id)
    work()
    work()
    d = payout(client, tenant_id, number)
    assert d["payout"]["status"] == "succeeded", d
    code = d["payout"]["code"]
    assert code.startswith("SORRY-") and d["label"].startswith(
        f"Voucher code {code} worth USD 15.00"
    )
    assert list(mock._state["codes"]) == [code]


def test_shopify_methods_need_a_connected_store(client: TestClient, tenant_id: str) -> None:
    response = client.put(
        f"/tenants/{tenant_id}/payouts/settings",
        json={"enabled": True, "methods": {"refund": "shopify_refund"}},
    )
    assert response.status_code == 409 and "Shopify" in response.json()["detail"]
