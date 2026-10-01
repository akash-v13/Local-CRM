"""API tests for case intake, lifecycle transitions and tenant isolation."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

CASE_PAYLOAD: dict[str, Any] = {
    "channel": "webform",
    "customer": {"email": "john.doe@example.com", "display_name": "John Doe", "tier": "Gold"},
    "category": {"type": "Complaint", "category": "Delivery", "subcategory": "Late delivery"},
    "message": "My order arrived almost a week late.",
    "attributes": {"orderNumber": "ORD-55012"},
}


def create_case(client: TestClient, tenant_id: str) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/cases", json=CASE_PAYLOAD)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def move(client: TestClient, tenant_id: str, case_number: int, to: str, **extra: Any) -> Any:
    return client.post(
        f"/tenants/{tenant_id}/cases/{case_number}/transitions",
        json={"to_status": to, "actor_type": "system", **extra},
    )


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_create_case_saves_message_and_routes_to_general_queue(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)

    # Every new tenant has a catch-all "General" queue, so the case is routed at intake.
    assert case["status"] == "Queued"
    assert case["queue"]["name"] == "General"
    assert case["category"]["customerSelected"]["category"] == "Delivery"
    assert case["category"]["effective"] == case["category"]["customerSelected"]
    assert case["attributes"] == {"orderNumber": "ORD-55012"}

    detail = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    assert [m["body"] for m in detail["messages"]] == [CASE_PAYLOAD["message"]]
    assert detail["messages"][0]["author_type"] == "customer"

    events = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}/events").json()
    assert [e["event_type"] for e in events] == [
        "case.created",
        "case.routed",
        "case.status_changed",
    ]
    assert events[1]["data"]["queueName"] == "General"
    assert (events[2]["from_status"], events[2]["to_status"]) == ("Intake", "Queued")


def test_same_email_reuses_customer(client: TestClient, tenant_id: str) -> None:
    first = create_case(client, tenant_id)
    second = create_case(client, tenant_id)
    assert first["customer_id"] == second["customer_id"]


def test_valid_transition_updates_status_and_records_event(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)

    response = move(client, tenant_id, case["case_number"], "AssignedAgent", reason="picking it up")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "AssignedAgent"
    assert response.json()["version"] == case["version"] + 1

    events = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}/events").json()
    assert events[-1]["event_type"] == "case.status_changed"
    assert (events[-1]["from_status"], events[-1]["to_status"]) == ("Queued", "AssignedAgent")
    assert events[-1]["reason"] == "picking it up"


def test_invalid_transition_is_rejected(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)

    response = move(client, tenant_id, case["case_number"], "Solved")
    assert response.status_code == 409
    assert "Cannot move a case from Queued to Solved" in response.json()["detail"]

    # Nothing changed.
    assert (
        client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()["status"] == "Queued"
    )


def test_stale_expected_version_is_rejected(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    assert move(client, tenant_id, case["case_number"], "AssignedAgent").status_code == 200

    response = move(
        client, tenant_id, case["case_number"], "Queued", expected_version=case["version"]
    )
    assert response.status_code == 409


def test_list_cases_filters_by_status(client: TestClient, tenant_id: str) -> None:
    first = create_case(client, tenant_id)
    create_case(client, tenant_id)
    move(client, tenant_id, first["case_number"], "AssignedAgent")

    assigned = client.get(f"/tenants/{tenant_id}/cases", params={"status": "AssignedAgent"}).json()
    assert [c["case_number"] for c in assigned] == [first["case_number"]]
    assert len(client.get(f"/tenants/{tenant_id}/cases").json()) == 2


def test_tenants_cannot_see_each_others_cases(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    other_tenant = client.post("/tenants", json={"name": "Other Co"}).json()["id"]

    assert client.get(f"/tenants/{other_tenant}/cases/{case['case_number']}").status_code == 404
    assert client.get(f"/tenants/{other_tenant}/cases").json() == []
    assert move(client, other_tenant, case["case_number"], "Queued").status_code == 404


def test_create_case_for_unknown_tenant_is_404(client: TestClient) -> None:
    response = client.post(f"/tenants/{uuid.uuid4()}/cases", json=CASE_PAYLOAD)
    assert response.status_code == 404
