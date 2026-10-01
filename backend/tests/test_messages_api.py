"""API tests for correspondence (agent replies, notes, customer replies), assignment,
the category taxonomy and tenant listing."""

from typing import Any

from fastapi.testclient import TestClient

from tests.test_cases_api import create_case, move

AGENT = "agent.alex"


def detail(client: TestClient, tenant_id: str, case_number: int) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{case_number}").json()
    return body


def post_message(client: TestClient, tenant_id: str, case_number: int, **body: Any) -> Any:
    return client.post(f"/tenants/{tenant_id}/cases/{case_number}/messages", json=body)


def assign_to_agent(client: TestClient, tenant_id: str, case_number: int) -> None:
    """New cases arrive Queued (routed to the General queue); take one as an agent."""
    response = client.post(
        f"/tenants/{tenant_id}/cases/{case_number}/transitions",
        json={"to_status": "AssignedAgent", "actor_type": "human", "actor_id": AGENT},
    )
    assert response.status_code == 200, response.text


def test_case_detail_includes_customer_and_allowed_next_statuses(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)
    d = detail(client, tenant_id, case["case_number"])

    assert d["customer"]["email"] == "john.doe@example.com"
    assert d["customer"]["display_name"] == "John Doe"
    assert d["allowed_next_statuses"] == ["AssignedAgent", "AssignedAI"]


def test_assigning_to_agent_records_assignee_and_queueing_clears_it(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)
    assign_to_agent(client, tenant_id, case["case_number"])
    d = detail(client, tenant_id, case["case_number"])
    assert (d["assignee_type"], d["assignee_id"]) == ("human", AGENT)

    move(client, tenant_id, case["case_number"], "Queued")  # manual reroute
    d = detail(client, tenant_id, case["case_number"])
    assert (d["assignee_type"], d["assignee_id"]) == (None, None)


def test_agent_reply_is_saved_as_outbound_public_message(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)
    response = post_message(
        client, tenant_id, case["case_number"], kind="agent_reply", body="Sorry!", author_id=AGENT
    )
    assert response.status_code == 201, response.text
    msg = response.json()
    assert (msg["direction"], msg["visibility"], msg["author_type"]) == (
        "outbound",
        "public",
        "human",
    )
    assert msg["author_id"] == AGENT

    d = detail(client, tenant_id, case["case_number"])
    assert [m["body"] for m in d["messages"]][-1] == "Sorry!"
    assert d["version"] == case["version"] + 1  # adding a message bumps the case version

    events = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}/events").json()
    assert events[-1]["event_type"] == "message.sent"
    assert events[-1]["data"]["delivery"] == "simulated"
    assert events[-1]["data"]["messageId"] == msg["id"]


def test_agent_reply_with_then_status_solves_in_one_step(
    client: TestClient, tenant_id: str
) -> None:
    case = create_case(client, tenant_id)
    assign_to_agent(client, tenant_id, case["case_number"])

    response = post_message(
        client,
        tenant_id,
        case["case_number"],
        kind="agent_reply",
        body="Refund issued.",
        author_id=AGENT,
        then_status="Solved",
    )
    assert response.status_code == 201, response.text
    assert detail(client, tenant_id, case["case_number"])["status"] == "Solved"


def test_reply_with_invalid_then_status_saves_nothing(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)  # Queued: can't jump straight to Solved

    response = post_message(
        client,
        tenant_id,
        case["case_number"],
        kind="agent_reply",
        body="Done",
        then_status="Solved",
    )
    assert response.status_code == 409
    d = detail(client, tenant_id, case["case_number"])
    assert len(d["messages"]) == 1  # the reply was rolled back with the failed transition
    assert d["status"] == "Queued"


def test_internal_note_is_internal(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    msg = post_message(
        client, tenant_id, case["case_number"], kind="internal_note", body="Checked with carrier."
    ).json()
    assert (msg["direction"], msg["visibility"], msg["channel"]) == ("internal", "internal", "note")


def test_customer_reply_on_solved_case_reopens_it(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    assign_to_agent(client, tenant_id, case["case_number"])
    post_message(
        client,
        tenant_id,
        case["case_number"],
        kind="agent_reply",
        body="Fixed",
        then_status="Solved",
    )

    response = post_message(
        client, tenant_id, case["case_number"], kind="customer_reply", body="Not yet!"
    )
    assert response.status_code == 201
    assert response.json()["author_type"] == "customer"

    d = detail(client, tenant_id, case["case_number"])
    assert d["status"] == "Queued"
    assert d["assignee_id"] is None


def test_closed_case_rejects_replies_but_allows_notes(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    assign_to_agent(client, tenant_id, case["case_number"])
    post_message(
        client, tenant_id, case["case_number"], kind="agent_reply", body="x", then_status="Solved"
    )
    assert move(client, tenant_id, case["case_number"], "Closed").status_code == 200

    for kind in ("customer_reply", "agent_reply"):
        response = post_message(client, tenant_id, case["case_number"], kind=kind, body="hello?")
        assert response.status_code == 409, kind
        assert "closed" in response.json()["detail"]

    assert (
        post_message(
            client, tenant_id, case["case_number"], kind="internal_note", body="ok"
        ).status_code
        == 201
    )


def test_messages_are_tenant_scoped(client: TestClient, tenant_id: str) -> None:
    case = create_case(client, tenant_id)
    other = client.post("/tenants", json={"name": "Other"}).json()["id"]
    response = post_message(client, other, case["case_number"], kind="internal_note", body="sneaky")
    assert response.status_code == 404


def test_categories_and_tenant_list(client: TestClient, tenant_id: str) -> None:
    taxonomy = client.get(f"/tenants/{tenant_id}/categories").json()
    assert "Complaint" in [t["name"] for t in taxonomy]
    complaint = next(t for t in taxonomy if t["name"] == "Complaint")
    delivery = next(c for c in complaint["categories"] if c["name"] == "Delivery")
    assert {"name": "Late delivery"} in delivery["subcategories"]

    assert tenant_id in [t["id"] for t in client.get("/tenants").json()]
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/tenants/{missing}/categories").status_code == 404
