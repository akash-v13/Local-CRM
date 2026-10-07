"""Automatic replies: drafted on arrival, sent after the delay unless a person steps in."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Case, Job
from app.services.enrichment import EnrichmentService
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver
from tests.test_ai_drafting import FakeWriter
from tests.test_cases_api import CASE_PAYLOAD

Work = Callable[..., None]


@pytest.fixture
def work(session_factory: sessionmaker[Session], fake_apis: FakeApis) -> Work:
    """Run due jobs. `later=True` first makes every waiting job due (time passes)."""

    def run(*, later: bool = False, writer: FakeWriter | None = None) -> None:
        if later:
            with session_factory() as session:
                for job in session.scalars(select(Job).where(Job.status == "pending")):
                    job.run_after = datetime.now(UTC) - timedelta(seconds=1)
                session.commit()
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=Settings(), resolve=public_resolver
            )
            while run_once(service, writer):
                pass

    return run


def auto_send(client: TestClient, tenant_id: str, **settings: Any) -> None:
    general = next(
        q for q in client.get(f"/tenants/{tenant_id}/queues").json() if q["name"] == "General"
    )
    response = client.patch(
        f"/tenants/{tenant_id}/queues/{general['id']}",
        json={"settings": {**general["settings"], "auto_send": True, **settings}},
    )
    assert response.status_code == 200, response.text


def rule(client: TestClient, tenant_id: str, outcome: dict[str, Any]) -> None:
    response = client.post(
        f"/tenants/{tenant_id}/compensation/rules",
        json={"name": "Late", "priority": 1, "outcome": outcome},
    )
    assert response.status_code == 201, response.text


def new_case(client: TestClient, tenant_id: str, **changes: Any) -> int:
    response = client.post(f"/tenants/{tenant_id}/cases", json={**CASE_PAYLOAD, **changes})
    assert response.status_code == 201, response.text
    number: int = response.json()["case_number"]
    return number


def case(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{number}").json()
    return body


def auto(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    state: dict[str, Any] = case(client, tenant_id, number)["decisions"].get("auto_reply") or {}
    return state


def sent(client: TestClient, tenant_id: str, number: int) -> list[dict[str, Any]]:
    return [m for m in case(client, tenant_id, number)["messages"] if m["direction"] == "outbound"]


def events(client: TestClient, tenant_id: str, number: int) -> list[str]:
    return [
        e["event_type"] for e in client.get(f"/tenants/{tenant_id}/cases/{number}/events").json()
    ]


def test_standard_reply_waits_then_sends(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id)
    rule(client, tenant_id, {"type": "store_credit", "amount": 10})
    number = new_case(client, tenant_id)
    work()

    state = auto(client, tenant_id, number)
    assert state["status"] == "scheduled" and state["mode"] == "template"
    wait = datetime.fromisoformat(state["send_at"]) - datetime.fromisoformat(state["scheduled_at"])
    assert wait == timedelta(hours=6)
    c = case(client, tenant_id, number)
    assert c["status"] == "AssignedAI"
    [draft] = [m for m in c["messages"] if m["visibility"] == "draft"]
    assert draft["body"].startswith(
        "Hi John,\n\nThank you for getting in touch about order ORD-55012"
    )
    assert "Here's what we've done: Store credit" in draft["body"]
    assert draft["body"].endswith("Best regards,\nNorthwind") or "Best regards," in draft["body"]

    work()  # not due yet
    assert sent(client, tenant_id, number) == []
    work(later=True)  # six hours later
    [reply] = sent(client, tenant_id, number)
    assert reply["author_type"] == "ai" and reply["author_id"] == "auto-reply"
    assert reply["body"] == draft["body"]
    assert case(client, tenant_id, number)["status"] == "Solved"
    assert auto(client, tenant_id, number)["status"] == "sent"
    e = events(client, tenant_id, number)
    assert e.index("auto_reply.scheduled") < e.index("auto_reply.sent") < e.index("message.sent")


def test_no_delay_sends_at_once(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id, auto_send_delay_minutes=0)
    rule(client, tenant_id, {"type": "none"})
    number = new_case(client, tenant_id)
    work()
    [reply] = sent(client, tenant_id, number)
    assert "Here's what we've done" not in reply["body"]  # nothing to offer, no empty sentence
    assert "sorry for the trouble.\n\nIf there's anything" in reply["body"]


def test_customer_writing_again_holds_it(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id)
    rule(client, tenant_id, {"type": "none"})
    number = new_case(client, tenant_id)
    work()
    client.post(
        f"/tenants/{tenant_id}/cases/{number}/messages",
        json={"kind": "customer_reply", "body": "Also, the box was crushed!"},
    )
    work(later=True)
    assert sent(client, tenant_id, number) == []
    state = auto(client, tenant_id, number)
    assert state["status"] == "held" and state["reason"] == "The customer wrote again."
    assert case(client, tenant_id, number)["status"] == "Queued"  # back for a person


def test_send_now_and_cancel(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id)
    rule(client, tenant_id, {"type": "none"})
    first, second = new_case(client, tenant_id), new_case(client, tenant_id)
    work()

    r = client.post(
        f"/tenants/{tenant_id}/cases/{first}/auto-reply/send-now", json={"actor_id": "owner"}
    )
    assert r.status_code == 200 and r.json()["released_by"] == "owner"
    work()  # no waiting
    assert len(sent(client, tenant_id, first)) == 1

    r = client.post(
        f"/tenants/{tenant_id}/cases/{second}/auto-reply/cancel", json={"actor_id": "owner"}
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    c = case(client, tenant_id, second)
    assert (c["status"], c["assignee_id"]) == ("AssignedAgent", "owner")
    assert any(m["visibility"] == "draft" for m in c["messages"])  # kept to edit and send

    work(later=True)  # six hours on: the original jobs send nothing more
    assert len(sent(client, tenant_id, first)) == 1
    assert sent(client, tenant_id, second) == []
    again = client.post(
        f"/tenants/{tenant_id}/cases/{second}/auto-reply/cancel", json={"actor_id": "x"}
    )
    assert again.status_code == 409


def test_someone_taking_the_case_stops_it(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id)
    rule(client, tenant_id, {"type": "none"})
    number = new_case(client, tenant_id)
    work()
    client.post(
        f"/tenants/{tenant_id}/cases/{number}/transitions",
        json={"to_status": "AssignedAgent", "actor_type": "human", "actor_id": "agent.alex"},
    )
    work(later=True)
    assert sent(client, tenant_id, number) == []
    assert auto(client, tenant_id, number)["status"] == "cancelled"


@pytest.mark.parametrize(
    ("outcome", "template", "reason"),
    [
        ({"type": "refund", "amount": 30, "requires_approval": True}, None, "waiting for approval"),
        (None, None, "No compensation rule matched this complaint."),
        ({"type": "none"}, "Hi {{enrichment.shop.daysLate}}", "{{enrichment.shop.daysLate}}"),
    ],
)
def test_held_for_a_person(
    client: TestClient,
    tenant_id: str,
    work: Work,
    outcome: dict[str, Any] | None,
    template: str | None,
    reason: str,
) -> None:
    auto_send(client, tenant_id, **({"auto_send_template": template} if template else {}))
    if outcome:
        rule(client, tenant_id, outcome)
    else:  # rules exist, but none matches this case
        response = client.post(
            f"/tenants/{tenant_id}/compensation/rules",
            json={
                "name": "Damaged only",
                "priority": 1,
                "match_criteria": {
                    "match": "all",
                    "conditions": [
                        {"field": "category.subcategory", "op": "equals", "value": "Damaged item"}
                    ],
                },
                "outcome": {"type": "voucher", "amount": 5},
            },
        )
        assert response.status_code == 201, response.text
    number = new_case(client, tenant_id)
    work(later=True)
    state = auto(client, tenant_id, number)
    assert state["status"] == "held" and reason in state["reason"]
    assert case(client, tenant_id, number)["status"] == "Queued"
    assert sent(client, tenant_id, number) == []
    assert "auto_reply.held" in events(client, tenant_id, number)


def test_waits_for_the_payout_so_it_can_quote_it(
    client: TestClient, tenant_id: str, work: Work, session_factory: sessionmaker[Session]
) -> None:
    auto_send(client, tenant_id, auto_send_delay_minutes=0)
    rule(client, tenant_id, {"type": "voucher", "amount": 15})
    number = new_case(client, tenant_id)

    def set_payout(status: str, label: str | None = None) -> None:
        with session_factory() as session:
            c = session.scalars(select(Case).where(Case.case_number == number)).one()
            decision = {**c.decisions["compensation"], "payout": {"status": status}}
            if label:
                decision["label"] = label
            c.decisions = {**c.decisions, "compensation": decision}
            session.commit()

    set_payout("processing")
    work()
    assert auto(client, tenant_id, number)["status"] == "preparing"  # waiting, not held
    set_payout("succeeded", "Voucher code SORRY-7KQ2MX worth USD 15.00 (single use)")
    work(later=True)
    [reply] = sent(client, tenant_id, number)
    assert "Voucher code SORRY-7KQ2MX" in reply["body"]


def test_ai_written_reply(client: TestClient, tenant_id: str, work: Work) -> None:
    auto_send(client, tenant_id, gen_ai_allowed=True, auto_send_mode="ai")
    rule(client, tenant_id, {"type": "none"})
    writer = FakeWriter()
    number = new_case(client, tenant_id)
    work(writer=writer)
    assert auto(client, tenant_id, number)["mode"] == "ai" and len(writer.calls) == 1
    work(later=True, writer=writer)
    [reply] = sent(client, tenant_id, number)
    assert reply["body"].startswith("Hi John, we're sorry your parcel was late.")  # unmasked

    other = new_case(client, tenant_id)
    work(later=True)  # no AI key in this worker
    assert "AI drafting isn't set up" in auto(client, tenant_id, other)["reason"]


def test_settings_validation_and_preview(client: TestClient, tenant_id: str) -> None:
    general = next(
        q for q in client.get(f"/tenants/{tenant_id}/queues").json() if q["name"] == "General"
    )
    url = f"/tenants/{tenant_id}/queues/{general['id']}"
    bad = {
        **general["settings"],
        "auto_send": True,
        "auto_send_mode": "ai",
        "gen_ai_allowed": False,
    }
    assert client.patch(url, json={"settings": bad}).status_code == 422
    unknown = {**general["settings"], "auto_send_template": "Hi {{secret.token}}"}
    response = client.patch(url, json={"settings": unknown})
    assert response.status_code == 422 and "{{secret.token}}" in response.text

    number = new_case(client, tenant_id)
    preview = client.post(
        f"/tenants/{tenant_id}/auto-reply/preview",
        json={"case_number": number, "template": "Hi {{customer.first_name}} ({{case.order}})"},
    )
    assert preview.json() == {"reply": "Hi John (order ORD-55012)"}
    missing = client.post(
        f"/tenants/{tenant_id}/auto-reply/preview",
        json={"case_number": number, "template": "{{enrichment.shop.x}}"},
    )
    assert missing.status_code == 409
