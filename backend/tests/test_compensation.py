"""Compensation matrix: the pure decision logic, then the API end to end."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.domain.compensation import PastCompensation, RuleCandidate, Settings, decide, describe
from tests.test_ai_drafting import FakeWriter, enable_ai_on_general, writer  # noqa: F401
from tests.test_cases_api import CASE_PAYLOAD

NOW = datetime(2026, 10, 5, tzinfo=UTC)
DELIVERY = {"conditions": [{"field": "category.category", "op": "equals", "value": "Delivery"}]}


def rule(name: str, priority: int, outcome: dict[str, Any], criteria: Any = None) -> RuleCandidate:
    return RuleCandidate(None, name, priority, NOW, criteria or {}, outcome)


def run(rules: list[RuleCandidate], context: dict[str, Any], **kw: Any) -> Any:
    kw.setdefault("history", [])
    kw.setdefault("settings", Settings())
    kw.setdefault("approval_threshold", None)
    return decide(rules, context, now=NOW, **kw)


# ----- pure decision logic --------------------------------------------------------------------


class TestDecide:
    ctx = {"category.category": "Delivery", "attributes.orderTotal": "240"}

    def test_first_matching_rule_by_priority_decides(self) -> None:
        refund = rule(
            "Half refund",
            20,
            {
                "type": "refund",
                "amount_mode": "percent",
                "percent": 50,
                "percent_of": "attributes.orderTotal",
            },
            DELIVERY,
        )
        voucher = rule("Voucher", 10, {"type": "voucher", "amount": 15}, DELIVERY)
        d = run([refund, voucher], self.ctx)
        assert d.rule is voucher and d.amount == 15 and not d.needs_approval
        assert d.label == "Voucher of USD 15.00"
        assert [e.matched for e in d.evaluations] == [True, True]  # every rule explained

    def test_percent_with_cap(self) -> None:
        r = rule(
            "Half refund",
            1,
            {
                "type": "refund",
                "amount_mode": "percent",
                "percent": 50,
                "percent_of": "attributes.orderTotal",
                "cap": 100,
            },
        )
        d = run([r], self.ctx)
        assert (
            d.amount == 100
            and "50% of attributes.orderTotal (240) = 120.00, capped" in d.amount_explanation
        )

    def test_missing_field_needs_approval(self) -> None:
        r = rule(
            "Half refund",
            1,
            {
                "type": "refund",
                "amount_mode": "percent",
                "percent": 50,
                "percent_of": "enrichment.shop.orderTotal",
            },
        )
        d = run([r], self.ctx)
        assert d.amount is None and d.needs_approval
        assert "isn't available" in d.approval_reasons[0]

    def test_threshold_rule_flag_and_repeat_claims(self) -> None:
        r = rule("Refund", 1, {"type": "refund", "amount": 80, "requires_approval": True})
        recent = PastCompensation(1, NOW - timedelta(days=10), "refund", 30)
        old = PastCompensation(2, NOW - timedelta(days=200), "refund", 30)
        d = run([r], self.ctx, approval_threshold=50, history=[recent, old])
        assert len(d.approval_reasons) == 3
        assert "always needs approval" in d.approval_reasons[0]
        assert "above the queue's approval threshold (50.00)" in d.approval_reasons[1]
        assert "compensated 1 time(s) in the last 90 days (total 30.00)" in d.approval_reasons[2]
        assert d.history == [recent]  # outside the window doesn't count

    def test_no_compensation_rule_and_no_match(self) -> None:
        none = rule(
            "Customer error",
            1,
            {"type": "none"},
            {
                "conditions": [
                    {"field": "attributes.reason", "op": "equals", "value": "wrong address"}
                ]
            },
        )
        assert run([none], {"attributes.reason": "wrong address"}).label is None
        assert run([none], {}).rule is None

    def test_labels(self) -> None:
        assert describe("points", 500, "USD") == "Loyalty points: 500 points"
        assert describe("replacement", None, "USD") == "Replacement"
        assert describe("none", None, "USD") is None


# ----- API --------------------------------------------------------------------------------------

REFUND: dict[str, Any] = {
    "name": "Late delivery refund",
    "priority": 10,
    "match_criteria": DELIVERY,
    "outcome": {
        "type": "refund",
        "amount_mode": "percent",
        "percent": 25,
        "percent_of": "attributes.orderTotal",
        "cap": 50,
    },
}


def base(tenant_id: str) -> str:
    return f"/tenants/{tenant_id}/compensation"


def new_case(
    client: TestClient, tenant_id: str, email: str = "john.doe@example.com", total: int = 120
) -> dict[str, Any]:
    body = {
        **CASE_PAYLOAD,
        "customer": {**CASE_PAYLOAD["customer"], "email": email},
        "attributes": {"orderNumber": "ORD-1", "orderTotal": total},
    }
    response = client.post(f"/tenants/{tenant_id}/cases", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def decision(client: TestClient, tenant_id: str, case: dict[str, Any]) -> Any:
    detail = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    return detail["decisions"].get("compensation")


def test_rules_crud_and_validation(client: TestClient, tenant_id: str) -> None:
    created = client.post(f"{base(tenant_id)}/rules", json=REFUND).json()
    replaced = client.put(
        f"{base(tenant_id)}/rules/{created['id']}", json={**REFUND, "is_active": False}
    ).json()
    assert replaced["is_active"] is False
    bad = {**REFUND, "outcome": {"type": "refund", "amount_mode": "percent", "percent": 10}}
    assert client.post(f"{base(tenant_id)}/rules", json=bad).status_code == 422
    unknown = {**REFUND, "outcome": {**REFUND["outcome"], "percent_of": "nope"}}
    assert client.post(f"{base(tenant_id)}/rules", json=unknown).status_code == 422


def test_no_rules_means_no_decision(client: TestClient, tenant_id: str) -> None:
    assert decision(client, tenant_id, new_case(client, tenant_id)) is None


def test_case_is_decided_when_routed_and_ai_gets_approved_compensation(
    client: TestClient,
    tenant_id: str,
    writer: FakeWriter,  # noqa: F811
) -> None:
    client.post(f"{base(tenant_id)}/rules", json=REFUND)
    case = new_case(client, tenant_id, total=120)
    d = decision(client, tenant_id, case)
    assert (d["status"], d["amount"], d["label"]) == ("approved", 30.0, "Refund of USD 30.00")
    assert d["matched_conditions"] == ['Category is "Delivery"']
    events = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}/events").json()
    assert any(e["event_type"] == "compensation.decided" for e in events)

    enable_ai_on_general(client, tenant_id)
    client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/drafts", json={})
    assert "Decided compensation: Refund of USD 30.00" in writer.calls[-1]["user"]


def test_approval_flow_and_pending_compensation_is_hidden_from_ai(
    client: TestClient,
    tenant_id: str,
    writer: FakeWriter,  # noqa: F811
) -> None:
    client.post(
        f"{base(tenant_id)}/rules",
        json={**REFUND, "outcome": {**REFUND["outcome"], "requires_approval": True}},
    )
    case = new_case(client, tenant_id)
    url = f"/tenants/{tenant_id}/cases/{case['case_number']}/compensation"
    assert decision(client, tenant_id, case)["status"] == "pending_approval"

    enable_ai_on_general(client, tenant_id)
    client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/drafts", json={})
    assert "Decided compensation: none; do not offer any" in writer.calls[-1]["user"]

    assert (
        client.post(f"{url}/reject", json={"actor_id": "mgr"}).status_code == 409
    )  # reason needed
    approved = client.post(f"{url}/approve", json={"actor_id": "mgr", "note": "ok"}).json()
    assert (approved["status"], approved["reviewed_by"]) == ("approved", "mgr")
    assert client.post(f"{url}/approve", json={"actor_id": "mgr"}).status_code == 409
    again = client.post(f"{url}/decide", json={"actor_id": "agent"})
    assert again.status_code == 409 and "already approved by mgr" in again.json()["detail"]


def test_repeat_claimant_and_queue_threshold(client: TestClient, tenant_id: str) -> None:
    client.post(f"{base(tenant_id)}/rules", json=REFUND)
    first = new_case(client, tenant_id)
    assert decision(client, tenant_id, first)["status"] == "approved"
    second = decision(client, tenant_id, new_case(client, tenant_id))
    assert second["status"] == "pending_approval"
    assert "Repeat claim" in second["approval_reasons"][0]
    assert second["history"][0]["case_number"] == first["case_number"]

    queue = client.get(f"/tenants/{tenant_id}/queues").json()[0]
    client.patch(
        f"/tenants/{tenant_id}/queues/{queue['id']}",
        json={"settings": {**queue["settings"], "approval_threshold": 20}},
    )
    other = decision(client, tenant_id, new_case(client, tenant_id, email="new@example.com"))
    assert other["status"] == "pending_approval"
    assert "above the queue's approval threshold (20.00)" in other["approval_reasons"][0]


def test_settings_preview_and_backtest(client: TestClient, tenant_id: str) -> None:
    client.put(
        f"{base(tenant_id)}/settings",
        json={"repeat_lookback_days": 30, "repeat_max_count": 2, "currency": "EUR"},
    )
    assert client.get(f"{base(tenant_id)}/settings").json()["currency"] == "EUR"
    cases = [new_case(client, tenant_id, total=t) for t in (100, 400, 80)]  # no rules yet

    draft = {**REFUND, "name": "Draft rule"}
    preview = client.post(
        f"{base(tenant_id)}/preview", json={"case_number": cases[0]["case_number"], "draft": draft}
    ).json()
    assert preview["decision"]["label"] == "Refund of EUR 25.00"
    assert preview["evaluations"][0]["is_draft"] is True
    assert decision(client, tenant_id, cases[0]) is None  # preview changes nothing

    result = client.post(f"{base(tenant_id)}/simulate", json={"days": 30, "draft": draft}).json()
    assert (result["cases_checked"], result["cases_matched"]) == (3, 3)
    [row] = result["rows"]
    # 25 + 50 (capped) + 20; the 3rd claim by the same customer exceeds 2 in 30 days.
    assert (row["cases"], row["total_amount"], row["needs_approval"]) == (3, 95.0, 1)
