"""Payouts through Stripe: a fake Stripe that behaves like the real one where it matters
(form-encoded requests, Bearer key, idempotency replay, error shapes)."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.payouts import get_payout_http
from app.config import Settings
from app.main import app
from app.models import Job
from app.payouts.stripe import StripeClient, StripeError, from_minor, to_minor
from app.services.enrichment import EnrichmentService
from app.services.payouts import CODE_ALPHABET, voucher_code
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver
from tests.test_cases_api import CASE_PAYLOAD

KEY = "sk_test_fake"


@dataclass
class FakeStripe:
    """Just enough of api.stripe.com: payments, customers, refunds, balance, coupons, codes."""

    intents: dict[str, dict[str, Any]] = field(default_factory=dict)
    customers: dict[str, dict[str, Any]] = field(default_factory=dict)
    refunds: list[dict[str, Any]] = field(default_factory=list)
    balance_txns: list[dict[str, Any]] = field(default_factory=list)
    coupons: list[dict[str, Any]] = field(default_factory=list)
    promos: list[dict[str, Any]] = field(default_factory=list)
    fail_next: list[int] = field(default_factory=list)  # status codes for the next POSTs
    replayed: dict[str, tuple[dict[str, str], httpx.Response]] = field(default_factory=dict)
    posts: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": {"message": "Invalid API Key provided"}})
        path, method = request.url.path, request.method
        if method == "GET":
            return self.get(path, dict(request.url.params))
        form = dict(parse_qsl(request.content.decode()))
        idem = request.headers.get("Idempotency-Key")
        if idem in self.replayed:
            original, response = self.replayed[idem]
            if original != form:
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "type": "idempotency_error",
                            "message": "Keys for idempotent requests can only be used "
                            "with the same parameters.",
                        }
                    },
                )
            return response
        self.posts.append({"path": path, "form": form, "key": idem})
        failure = self.fail_next.pop(0) if self.fail_next else None
        if failure == 0:  # the connection drops before Stripe answers (nothing saved)
            self.posts.pop()
            raise httpx.ConnectError("connection reset")
        if failure is not None and failure >= 1000:  # Stripe did it, then answered 500
            self.post(path, form)
            failure -= 1000
        response = (
            httpx.Response(failure, json={"error": {"message": "Temporary problem"}})
            if failure is not None
            else self.post(path, form)
        )
        if idem and response.status_code != 429:  # rate limits happen before the request runs
            self.replayed[idem] = (form, response)
        return response

    def get(self, path: str, params: dict[str, str]) -> httpx.Response:
        if path == "/v1/balance":
            return httpx.Response(
                200, json={"livemode": False, "available": [{"currency": "usd", "amount": 10000}]}
            )
        if path == "/v1/payment_intents/search":
            key, _, value = params["query"].removeprefix("metadata['").partition("']:'")
            found = [
                pi for pi in self.intents.values() if pi["metadata"].get(key) == value.rstrip("'")
            ]
            return httpx.Response(200, json={"data": found})
        if path.startswith("/v1/payment_intents/"):
            pi = self.intents.get(path.rsplit("/", 1)[1])
            return (
                httpx.Response(200, json=pi)
                if pi
                else httpx.Response(404, json={"error": {"message": "No such payment_intent"}})
            )
        if path == "/v1/refunds":
            intent_id = params.get("payment_intent")
            refunds = [r for r in self.refunds if r["payment_intent"] == intent_id]
            return httpx.Response(200, json={"data": refunds})
        if path.endswith("/balance_transactions"):
            return httpx.Response(200, json={"data": self.balance_txns})
        if path == "/v1/promotion_codes":
            promos = [p for p in self.promos if p["code"] == params.get("code")]
            return httpx.Response(200, json={"data": promos})
        if path == "/v1/customers":
            found = [c for c in self.customers.values() if c["email"] == params.get("email")]
            return httpx.Response(200, json={"data": found})
        return httpx.Response(404, json={"error": {"message": "Unrecognized request URL"}})

    def post(self, path: str, form: dict[str, str]) -> httpx.Response:
        if path == "/v1/refunds":
            pi = self.intents.get(form.get("payment_intent", ""))
            if pi is None:
                return httpx.Response(
                    400,
                    json={
                        "error": {"code": "resource_missing", "message": "No such payment_intent"}
                    },
                )
            refund = {
                **form,
                "id": f"re_{len(self.refunds) + 1}",
                "amount": int(form["amount"]),
                "status": "succeeded",
                "metadata": _metadata(form),
            }
            self.refunds.append(refund)
            return httpx.Response(200, json=refund)
        if path.endswith("/balance_transactions"):
            txn = {
                **form,
                "id": f"cbtxn_{len(self.balance_txns) + 1}",
                "amount": int(form["amount"]),
                "ending_balance": int(form["amount"]),
                "metadata": _metadata(form),
            }
            self.balance_txns.append(txn)
            return httpx.Response(200, json=txn)
        if path == "/v1/coupons":
            coupon = {"id": f"co_{len(self.coupons) + 1}", **form}
            self.coupons.append(coupon)
            return httpx.Response(200, json=coupon)
        if path == "/v1/promotion_codes":
            promo = {
                **form,
                "id": f"promo_{len(self.promos) + 1}",
                "promotion": {"type": "coupon", "coupon": form.get("promotion[coupon]")},
            }
            self.promos.append(promo)
            return httpx.Response(200, json=promo)
        return httpx.Response(404, json={"error": {"message": "Unrecognized request URL"}})


def _metadata(form: dict[str, str]) -> dict[str, str]:
    return {k[9:-1]: v for k, v in form.items() if k.startswith("metadata[")}


# ----- units -------------------------------------------------------------------------------


def test_minor_units() -> None:
    assert to_minor(19.99, "USD") == 1999 and to_minor(89.52, "usd") == 8952
    assert to_minor(1500, "JPY") == 1500 and from_minor(1999, "usd") == 19.99


def test_voucher_codes_are_stable_and_readable() -> None:
    a, b = voucher_code("SORRY", "lcrm:x:1"), voucher_code("SORRY", "lcrm:x:1")
    assert a == b and a.startswith("SORRY-") and len(a) == 12
    assert all(ch in CODE_ALPHABET for ch in a.split("-")[1])
    assert voucher_code("SORRY", "lcrm:x:2") != a


def test_client_sends_form_bearer_and_idempotency_key() -> None:
    stripe = FakeStripe(intents={"pi_1": {"id": "pi_1", "currency": "usd", "metadata": {}}})
    client = StripeClient(httpx.Client(transport=httpx.MockTransport(stripe)), KEY)
    client.refund(payment_intent="pi_1", amount=500, metadata={"case": "1"}, idempotency_key="k1")
    client.refund(payment_intent="pi_1", amount=500, metadata={"case": "1"}, idempotency_key="k1")
    assert len(stripe.refunds) == 1  # the retry was replayed, not repeated
    assert stripe.posts[0]["form"] == {
        "payment_intent": "pi_1",
        "amount": "500",
        "reason": "requested_by_customer",
        "metadata[case]": "1",
    }
    with pytest.raises(StripeError, match="same parameters"):
        client.refund(payment_intent="pi_1", amount=600, metadata={}, idempotency_key="k1")


@pytest.mark.parametrize(
    ("status", "retryable", "message"),
    [
        (401, False, "API key"),
        (429, True, "Temporary"),
        (500, True, "Temporary"),
        (402, False, "Temporary"),
    ],
)
def test_client_error_mapping(status: int, retryable: bool, message: str) -> None:
    stripe = FakeStripe(fail_next=[status])
    key = "bad" if status == 401 else KEY
    client = StripeClient(httpx.Client(transport=httpx.MockTransport(stripe)), key)
    with pytest.raises(StripeError, match=message) as exc:
        client.credit_customer(
            customer="cus_1",
            amount=1,
            currency="usd",
            description="x",
            metadata={},
            idempotency_key="k",
        )
    assert exc.value.retryable is retryable


# ----- end to end -------------------------------------------------------------------------


@pytest.fixture
def stripe(client: TestClient, fake_apis: FakeApis) -> FakeStripe:
    fake = FakeStripe(
        intents={
            "pi_55012": {"id": "pi_55012", "currency": "usd", "metadata": {"order_id": "ORD-55012"}}
        },
        customers={"cus_1": {"id": "cus_1", "email": "john.doe@example.com"}},
    )
    fake_apis.handler = fake

    def stripe_http() -> Iterator[httpx.Client]:
        with httpx.Client(transport=httpx.MockTransport(fake)) as http:
            yield http

    app.dependency_overrides[get_payout_http] = stripe_http
    return fake


@pytest.fixture
def work(session_factory: sessionmaker[Session], fake_apis: FakeApis) -> Callable[[], None]:
    def run() -> None:
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=Settings(), resolve=public_resolver
            )
            while run_once(service):
                pass

    return run


def setup(
    client: TestClient, tenant_id: str, outcome: dict[str, Any], **payout_settings: Any
) -> str:
    credential = client.post(
        f"/tenants/{tenant_id}/credentials",
        json={"name": "Stripe", "kind": "bearer", "secrets": {"token": KEY}},
    ).json()
    client.post(
        f"/tenants/{tenant_id}/compensation/rules",
        json={"name": "Late", "priority": 1, "outcome": outcome},
    )
    settings = {"enabled": True, "credential_id": credential["id"], **payout_settings}
    response = client.put(f"/tenants/{tenant_id}/payouts/settings", json=settings)
    assert response.status_code == 200, response.text
    return str(credential["id"])


def new_case(client: TestClient, tenant_id: str) -> int:
    number: int = client.post(f"/tenants/{tenant_id}/cases", json=CASE_PAYLOAD).json()[
        "case_number"
    ]
    return number


def decision(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{number}").json()["decisions"][
        "compensation"
    ]
    return result


def test_approved_refund_is_issued_once(
    client: TestClient,
    tenant_id: str,
    stripe: FakeStripe,
    work: Callable[[], None],
    session_factory: sessionmaker[Session],
) -> None:
    setup(client, tenant_id, {"type": "refund", "amount": 30})
    number = new_case(client, tenant_id)  # approved automatically → payout queued
    assert decision(client, tenant_id, number)["payout"]["status"] == "queued"
    work()

    [refund] = stripe.refunds
    assert (refund["payment_intent"], refund["amount"]) == (
        "pi_55012",
        3000,
    )  # found by metadata order_id
    assert refund["metadata[case_number]"] == str(number)
    d = decision(client, tenant_id, number)
    assert d["payout"]["status"] == "succeeded" and d["payout"]["external_id"] == "re_1"
    assert d["label"] == "Refund of USD 30.00 (issued to the original payment)"
    [payout] = client.get(f"/tenants/{tenant_id}/cases/{number}/payouts").json()
    assert payout["details"]["payment_intent"] == "pi_55012" and payout["attempts"] == 1
    events = [
        e["event_type"] for e in client.get(f"/tenants/{tenant_id}/cases/{number}/events").json()
    ]
    assert events.index("payout.queued") < events.index("payout.succeeded")

    # A duplicate job (e.g. a crash after the refund) doesn't pay again.
    with session_factory() as session:
        session.add(
            Job(
                tenant_id=uuid.UUID(tenant_id),
                kind="issue_payout",
                payload={"payout_id": payout["id"]},
            )
        )
        session.commit()
    work()
    assert len(stripe.refunds) == 1
    assert (
        client.post(
            f"/tenants/{tenant_id}/cases/{number}/payouts", json={"actor_id": "a"}
        ).status_code
        == 409
    )
    rows = client.get(f"/tenants/{tenant_id}/payouts").json()
    assert rows[0]["case_number"] == number and rows[0]["customer_email"] == "john.doe@example.com"


def _skip_backoff(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        for job in session.scalars(select(Job).where(Job.kind == "issue_payout")):
            job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()


@pytest.mark.parametrize(
    ("failure", "refund_calls", "same_key"),
    [
        (0, 1, True),  # network drop: nothing reached Stripe; retried with the same key
        (429, 2, True),  # rate limited: retried with the same key
        (500, 2, False),  # failed with 500: Stripe checked first, then a fresh key
        (1500, 1, None),  # done but answered 500: found by payout_id, not paid again
    ],
)
def test_retries_never_pay_twice(
    client: TestClient,
    tenant_id: str,
    stripe: FakeStripe,
    work: Callable[[], None],
    session_factory: sessionmaker[Session],
    failure: int,
    refund_calls: int,
    same_key: bool | None,
) -> None:
    setup(client, tenant_id, {"type": "refund", "amount": 30})
    stripe.fail_next = [failure]
    number = new_case(client, tenant_id)
    work()
    assert decision(client, tenant_id, number)["payout"]["status"] == "retrying"
    _skip_backoff(session_factory)
    work()
    assert decision(client, tenant_id, number)["payout"]["status"] == "succeeded"
    assert len(stripe.refunds) == 1
    keys = [p["key"] for p in stripe.posts if p["path"] == "/v1/refunds"]
    assert len(keys) == refund_calls
    if same_key is not None:
        assert (keys[0] == keys[-1]) is same_key


def test_failures_explain_and_can_be_retried_after_fixing(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    setup(client, tenant_id, {"type": "refund", "amount": 30})
    missing = stripe.intents.pop("pi_55012")
    number = new_case(client, tenant_id)
    work()
    d = decision(client, tenant_id, number)
    assert (
        d["payout"]["status"] == "failed"
        and "Couldn't find the Stripe payment for order ORD-55012" in d["payout"]["error"]
    )
    assert d["label"] == "Refund of USD 30.00"  # not claimed as issued

    stripe.intents["pi_55012"] = missing  # fixed (e.g. metadata added in Stripe)
    retry = client.post(
        f"/tenants/{tenant_id}/cases/{number}/payouts", json={"actor_id": "agent.alex"}
    ).json()
    assert retry["status"] == "queued" and retry["created_by"] == "agent.alex"
    work()
    assert (
        decision(client, tenant_id, number)["payout"]["status"] == "succeeded"
        and len(stripe.refunds) == 1
    )


def test_currency_mismatch_is_refused(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    setup(client, tenant_id, {"type": "refund", "amount": 30, "currency": "EUR"})
    number = new_case(client, tenant_id)
    work()
    assert (
        "The payment was in USD, the refund in EUR"
        in decision(client, tenant_id, number)["payout"]["error"]
    )
    assert stripe.refunds == []


def test_payment_from_a_case_field(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    stripe.intents["pi_other"] = {"id": "pi_other", "currency": "usd", "metadata": {}}
    setup(client, tenant_id, {"type": "refund", "amount": 30}, payment_field="attributes.paymentId")
    number = client.post(
        f"/tenants/{tenant_id}/cases",
        json={**CASE_PAYLOAD, "attributes": {"orderNumber": "ORD-55012", "paymentId": "pi_other"}},
    ).json()["case_number"]
    work()
    assert stripe.refunds[0]["payment_intent"] == "pi_other"
    assert decision(client, tenant_id, number)["payout"]["status"] == "succeeded"


def test_store_credit_and_voucher(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    setup(client, tenant_id, {"type": "store_credit", "amount": 12.5})
    number = new_case(client, tenant_id)
    work()
    [txn] = stripe.balance_txns
    assert (txn["amount"], txn["currency"]) == (-1250, "usd")  # negative = credit
    assert decision(client, tenant_id, number)["payout"]["status"] == "succeeded"

    rule = client.get(f"/tenants/{tenant_id}/compensation/rules").json()[0]
    client.put(
        f"/tenants/{tenant_id}/compensation/rules/{rule['id']}",
        json={**rule, "outcome": {"type": "voucher", "amount": 15}},
    )
    client.put(
        f"/tenants/{tenant_id}/compensation/settings",
        json={"repeat_lookback_days": 1, "repeat_max_count": 5, "currency": "USD"},
    )
    number = new_case(client, tenant_id)
    work()
    [coupon], [promo] = stripe.coupons, stripe.promos
    assert (coupon["amount_off"], coupon["duration"], coupon["max_redemptions"]) == (
        "1500",
        "once",
        "1",
    )
    assert promo["promotion[type]"] == "coupon" and promo["promotion[coupon]"] == coupon["id"]
    assert (
        promo["customer"] == "cus_1" and promo["code"].startswith("SORRY-") and promo["expires_at"]
    )
    d = decision(client, tenant_id, number)
    assert d["label"].startswith(
        f"Voucher code {promo['code']} worth USD 15.00 (single use, valid until "
    )


def test_approval_gates_payment_and_manual_mode(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    setup(
        client,
        tenant_id,
        {"type": "refund", "amount": 30, "requires_approval": True},
        auto_pay=False,
    )
    number = new_case(client, tenant_id)
    work()
    assert decision(client, tenant_id, number)["payout"] is None and stripe.refunds == []
    assert (
        client.post(
            f"/tenants/{tenant_id}/cases/{number}/payouts", json={"actor_id": "a"}
        ).status_code
        == 409
    )  # not approved
    client.post(
        f"/tenants/{tenant_id}/cases/{number}/compensation/approve", json={"actor_id": "mgr"}
    )
    assert decision(client, tenant_id, number)["payout"] is None  # auto_pay off
    client.post(f"/tenants/{tenant_id}/cases/{number}/payouts", json={"actor_id": "mgr"})
    work()
    assert len(stripe.refunds) == 1


def test_approving_pays_automatically(
    client: TestClient, tenant_id: str, stripe: FakeStripe, work: Callable[[], None]
) -> None:
    setup(client, tenant_id, {"type": "refund", "amount": 30, "requires_approval": True})
    number = new_case(client, tenant_id)
    approved = client.post(
        f"/tenants/{tenant_id}/cases/{number}/compensation/approve", json={"actor_id": "mgr"}
    ).json()
    assert approved["payout"]["status"] == "queued"
    work()
    assert len(stripe.refunds) == 1


def test_pipeline_shows_payouts(client: TestClient, tenant_id: str) -> None:
    assert client.get(f"/tenants/{tenant_id}/pipeline").json()["payouts"] is None
    setup(
        client,
        tenant_id,
        {"type": "refund", "amount": 30},
        methods={"refund": "stripe_refund", "voucher": "manual"},
    )
    payouts = client.get(f"/tenants/{tenant_id}/pipeline").json()["payouts"]
    assert payouts == {
        "provider": "stripe",
        "auto_pay": True,
        "methods": {"refund": "stripe_refund"},
    }


def test_settings_validation_and_stripe_check(
    client: TestClient, tenant_id: str, stripe: FakeStripe
) -> None:
    credential = setup(client, tenant_id, {"type": "replacement"})
    url = f"/tenants/{tenant_id}/payouts/settings"
    assert client.put(url, json={"enabled": True}).status_code == 422  # no credential
    assert (
        client.put(
            url, json={"credential_id": credential, "methods": {"refund": "stripe_voucher"}}
        ).status_code
        == 422
    )
    assert (
        client.put(url, json={"credential_id": credential, "payment_field": "nope"}).status_code
        == 422
    )
    check = client.post(
        f"/tenants/{tenant_id}/payouts/check-stripe", json={"credential_id": credential}
    ).json()
    assert check["ok"] and check["mode"] == "test" and "USD" in check["detail"]
    bad = client.post(
        f"/tenants/{tenant_id}/credentials",
        json={"name": "Bad", "kind": "bearer", "secrets": {"token": "sk_test_wrong"}},
    ).json()
    failed = client.post(
        f"/tenants/{tenant_id}/payouts/check-stripe", json={"credential_id": bad["id"]}
    ).json()
    assert not failed["ok"] and "rejected the API key" in failed["detail"]
    number = new_case(client, tenant_id)  # replacement: not a payment, so nothing to pay
    assert (
        client.post(
            f"/tenants/{tenant_id}/cases/{number}/payouts", json={"actor_id": "a"}
        ).status_code
        == 409
    )


def test_demo_mock_stripe_speaks_the_same_api() -> None:
    """The fake Stripe in mocks/shop.py (used by docker compose) works with StripeClient."""
    from mocks.shop import app as mock_app

    mock = TestClient(mock_app)

    def forward(request: httpx.Request) -> httpx.Response:
        response = mock.request(
            request.method, str(request.url), content=request.content, headers=request.headers
        )
        return httpx.Response(response.status_code, content=response.content)

    with httpx.Client(transport=httpx.MockTransport(forward)) as http:
        stripe = StripeClient(http, "sk_test_mock", "http://testserver/stripe")
        assert stripe.account().mode == "test"
        intent = stripe.find_payment_by_metadata("order_id", "NW-10211")
        assert intent == "pi_mock_NW_10211"
        meta = {"payout_id": "p1"}
        first = stripe.refund(
            payment_intent=intent, amount=500, metadata=meta, idempotency_key="k1"
        )
        again = stripe.refund(
            payment_intent=intent, amount=500, metadata=meta, idempotency_key="k1"
        )
        assert first["id"] == again["id"]
        assert stripe.find_refund(intent, "p1") is not None
        customer = stripe.find_customer("priya@example.com")
        assert customer
        _, promo = stripe.voucher(
            amount=1500, currency="usd", code="SORRY-TEST", customer=customer, expires_at=None,
            name="Sorry", metadata=meta, idempotency_key="k2",
        )  # fmt: skip
        assert stripe.find_promotion_code("SORRY-TEST") == promo
        with pytest.raises(StripeError, match="API key"):
            StripeClient(http, "sk_test_wrong", "http://testserver/stripe").account()
