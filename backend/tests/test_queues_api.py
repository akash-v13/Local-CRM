"""API tests for queues, automatic routing, manual reroute, routing preview and the queue report."""

from typing import Any

from fastapi.testclient import TestClient

from tests.test_cases_api import CASE_PAYLOAD, move

DELIVERY_RULE = {
    "match": "all",
    "conditions": [{"field": "category.category", "op": "equals", "value": "Delivery"}],
}


def create_queue(
    client: TestClient,
    tenant_id: str,
    name: str,
    priority: int,
    criteria: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body = {"name": name, "priority": priority, "match_criteria": criteria or {}, **extra}
    response = client.post(f"/tenants/{tenant_id}/queues", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def new_case(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/cases", json={**CASE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def queues(client: TestClient, tenant_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"/tenants/{tenant_id}/queues").json()
    return result


def events(client: TestClient, tenant_id: str, case_number: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(
        f"/tenants/{tenant_id}/cases/{case_number}/events"
    ).json()
    return result


def general_id(client: TestClient, tenant_id: str) -> str:
    return str(next(q["id"] for q in queues(client, tenant_id) if q["name"] == "General"))


# ----- queue management --------------------------------------------------------------------


def test_new_tenant_gets_catch_all_general_queue(client: TestClient, tenant_id: str) -> None:
    [general] = queues(client, tenant_id)
    assert general["name"] == "General"
    assert general["priority"] == 1000
    assert general["match_criteria"] == {"match": "all", "conditions": []}
    assert general["settings"]["reopen_window_hours"] == 72


def test_queues_are_listed_in_routing_order(client: TestClient, tenant_id: str) -> None:
    create_queue(client, tenant_id, "B", 20)
    create_queue(client, tenant_id, "A", 10)
    assert [q["name"] for q in queues(client, tenant_id)] == ["A", "B", "General"]


def test_invalid_criteria_are_rejected(client: TestClient, tenant_id: str) -> None:
    bad = [
        {"field": "customer.email", "op": "equals", "value": "x"},  # unknown field
        {"field": "channel", "op": "one_of", "value": []},  # list op needs values
        {"field": "channel", "op": "equals", "value": ["a", "b"]},  # single-value op got a list
        {"field": "channel", "op": "equals", "value": "  "},  # blank
        {"field": "channel", "op": "matches_regex", "value": "x"},  # unknown operator
    ]
    for condition in bad:
        response = client.post(
            f"/tenants/{tenant_id}/queues",
            json={"name": "Bad", "priority": 1, "match_criteria": {"conditions": [condition]}},
        )
        assert response.status_code == 422, condition


def test_update_is_partial(client: TestClient, tenant_id: str) -> None:
    queue = create_queue(
        client, tenant_id, "Delivery", 10, DELIVERY_RULE, settings={"gen_ai_allowed": True}
    )
    response = client.patch(f"/tenants/{tenant_id}/queues/{queue['id']}", json={"priority": 5})
    assert response.status_code == 200
    updated = response.json()
    assert updated["priority"] == 5
    assert updated["match_criteria"] == queue["match_criteria"]
    assert updated["settings"]["gen_ai_allowed"] is True


def test_queues_are_tenant_scoped(client: TestClient, tenant_id: str) -> None:
    queue = create_queue(client, tenant_id, "Mine", 10)
    other = client.post("/tenants", json={"name": "Other"}).json()["id"]
    assert client.get(f"/tenants/{other}/queues/{queue['id']}").status_code == 404
    assert (
        client.patch(f"/tenants/{other}/queues/{queue['id']}", json={"priority": 1}).status_code
        == 404
    )


# ----- automatic routing -------------------------------------------------------------------


def test_matching_case_goes_to_matching_queue_and_records_why(
    client: TestClient, tenant_id: str
) -> None:
    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)

    case = new_case(client, tenant_id)
    assert case["queue"]["name"] == "Delivery"

    routed = next(
        e
        for e in events(client, tenant_id, case["case_number"])
        if e["event_type"] == "case.routed"
    )
    assert routed["data"]["matchedConditions"] == ['Category is "Delivery"']


def test_non_matching_case_falls_through_to_general(client: TestClient, tenant_id: str) -> None:
    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    case = new_case(
        client,
        tenant_id,
        category={"type": "Question", "category": "Refund", "subcategory": "Refund status"},
    )
    assert case["queue"]["name"] == "General"


def test_lower_priority_number_wins_and_inactive_queues_are_skipped(
    client: TestClient, tenant_id: str
) -> None:
    create_queue(client, tenant_id, "Delivery", 20, DELIVERY_RULE)
    keyword_rule = {"conditions": [{"field": "message", "op": "contains_any", "value": ["late"]}]}
    create_queue(client, tenant_id, "Late (inactive)", 5, keyword_rule, is_active=False)
    create_queue(client, tenant_id, "Late", 10, keyword_rule)

    # CASE_PAYLOAD's message: "My order arrived almost a week late."
    assert new_case(client, tenant_id)["queue"]["name"] == "Late"


def test_no_matching_queue_leaves_case_in_intake_until_routed_again(
    client: TestClient, tenant_id: str
) -> None:
    client.patch(
        f"/tenants/{tenant_id}/queues/{general_id(client, tenant_id)}", json={"is_active": False}
    )

    case = new_case(client, tenant_id)
    assert case["status"] == "Intake"
    assert case["queue"] is None
    assert events(client, tenant_id, case["case_number"])[-1]["event_type"] == "case.unrouted"

    unrouted = client.get(f"/tenants/{tenant_id}/cases", params={"unrouted": "true"}).json()
    assert [c["case_number"] for c in unrouted] == [case["case_number"]]

    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    response = client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/route", json={})
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["queue"]["name"]) == ("Queued", "Delivery")


def test_route_again_picks_up_changed_rules(client: TestClient, tenant_id: str) -> None:
    case = new_case(client, tenant_id)
    assert case["queue"]["name"] == "General"

    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    routed = client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/route", json={}).json()
    assert routed["queue"]["name"] == "Delivery"

    assign = move(client, tenant_id, case["case_number"], "AssignedAgent")
    assert assign.status_code == 200
    response = client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/route", json={})
    assert response.status_code == 409  # being worked on: no automatic re-routing


def test_queue_filter_on_case_list(client: TestClient, tenant_id: str) -> None:
    delivery = create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    in_delivery = new_case(client, tenant_id)
    new_case(client, tenant_id, category={"type": "Question", "category": "Refund"})

    listed = client.get(f"/tenants/{tenant_id}/cases", params={"queue_id": delivery["id"]}).json()
    assert [c["case_number"] for c in listed] == [in_delivery["case_number"]]


# ----- manual reroute ----------------------------------------------------------------------


def test_reroute_moves_pins_and_records(client: TestClient, tenant_id: str) -> None:
    case = new_case(client, tenant_id)  # → General
    vip = create_queue(client, tenant_id, "VIP", 50)
    move(client, tenant_id, case["case_number"], "AssignedAgent")

    response = client.post(
        f"/tenants/{tenant_id}/cases/{case['case_number']}/reroute",
        json={"queue_id": vip["id"], "actor_id": "agent.alex", "reason": "Top customer"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["queue"]["name"], body["assignment_pinned"]) == (
        "Queued",
        "VIP",
        True,
    )
    assert body["assignee_id"] is None

    rerouted = events(client, tenant_id, case["case_number"])[-1]
    assert rerouted["event_type"] == "case.rerouted"
    assert (rerouted["data"]["fromQueueName"], rerouted["data"]["toQueueName"]) == (
        "General",
        "VIP",
    )
    assert rerouted["reason"] == "Top customer"

    # Pinned: automatic routing refuses to move it.
    assert (
        client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/route", json={}).status_code
        == 409
    )


def test_reroute_rejects_inactive_foreign_and_closed(client: TestClient, tenant_id: str) -> None:
    inactive = create_queue(client, tenant_id, "Old", 50, is_active=False)
    case = new_case(client, tenant_id)
    url = f"/tenants/{tenant_id}/cases/{case['case_number']}/reroute"

    assert client.post(url, json={"queue_id": inactive["id"]}).status_code == 409

    other = client.post("/tenants", json={"name": "Other"}).json()["id"]
    foreign = create_queue(client, other, "Theirs", 10)
    assert client.post(url, json={"queue_id": foreign["id"]}).status_code == 404

    move(client, tenant_id, case["case_number"], "AssignedAgent")
    move(client, tenant_id, case["case_number"], "Solved")
    move(client, tenant_id, case["case_number"], "Closed")
    assert client.post(url, json={"queue_id": general_id(client, tenant_id)}).status_code == 409


# ----- preview -----------------------------------------------------------------------------


def test_preview_explains_every_queue(client: TestClient, tenant_id: str) -> None:
    create_queue(
        client,
        tenant_id,
        "Email only",
        5,
        {"conditions": [{"field": "channel", "op": "equals", "value": "email"}]},
    )
    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    case = new_case(client, tenant_id)

    preview = client.post(
        f"/tenants/{tenant_id}/routing/preview", json={"case_number": case["case_number"]}
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["winner_queue_name"] == "Delivery"
    assert [(e["queue_name"], e["matched"], e["is_winner"]) for e in body["evaluations"]] == [
        ("Email only", False, False),
        ("Delivery", True, True),
        ("General", True, False),
    ]
    email_condition = body["evaluations"][0]["conditions"][0]
    assert email_condition["actual"] == "webform"
    assert email_condition["description"] == 'Channel is "email"'


def test_preview_with_unsaved_draft_changes_nothing(client: TestClient, tenant_id: str) -> None:
    delivery = create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    case = new_case(client, tenant_id)

    # Draft edit: make Delivery only match emails. The case would then fall through to General.
    draft = {
        "name": "Delivery",
        "priority": 10,
        "match_criteria": {"conditions": [{"field": "channel", "op": "equals", "value": "email"}]},
    }
    body = client.post(
        f"/tenants/{tenant_id}/routing/preview",
        json={
            "case_number": case["case_number"],
            "draft": draft,
            "draft_queue_id": delivery["id"],
        },
    ).json()
    assert body["winner_queue_name"] == "General"
    assert [e["is_draft"] for e in body["evaluations"]] == [True, False]

    # A brand-new draft queue that would win.
    new_draft = {"name": "Brand new", "priority": 1, "match_criteria": {}}
    body = client.post(
        f"/tenants/{tenant_id}/routing/preview",
        json={"case_number": case["case_number"], "draft": new_draft},
    ).json()
    assert body["winner_queue_name"] == "Brand new"
    assert body["winner_queue_id"] is None

    # Nothing was saved.
    assert [q["name"] for q in queues(client, tenant_id)] == ["Delivery", "General"]
    assert (
        client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()["queue"]["name"]
        == "Delivery"
    )


def test_routing_fields_offer_suggestions(client: TestClient, tenant_id: str) -> None:
    new_case(client, tenant_id)  # customer tier "Gold"
    body = client.get(f"/tenants/{tenant_id}/routing/fields").json()
    fields = {f["key"]: f for f in body["fields"]}
    assert "Delivery" in fields["category.category"]["suggestions"]
    assert fields["customer.tier"]["suggestions"] == ["Gold"]
    ops = {o["key"]: o["takes_list"] for o in body["operators"]}
    assert ops == {
        "equals": False,
        "not_equals": False,
        "one_of": True,
        "contains_any": True,
        "greater_than": False,
        "less_than": False,
    }


# ----- report ------------------------------------------------------------------------------


def test_queue_report_counts_by_queue_and_status(client: TestClient, tenant_id: str) -> None:
    create_queue(client, tenant_id, "Delivery", 10, DELIVERY_RULE)
    create_queue(
        client,
        tenant_id,
        "Empty",
        20,
        {"conditions": [{"field": "channel", "op": "equals", "value": "chat"}]},
    )

    a = new_case(client, tenant_id)  # → Delivery
    b = new_case(client, tenant_id)  # → Delivery
    new_case(client, tenant_id, category={"type": "Question", "category": "Refund"})  # → General
    move(client, tenant_id, a["case_number"], "AssignedAgent")
    move(client, tenant_id, a["case_number"], "WaitingApproval")
    move(client, tenant_id, b["case_number"], "AssignedAgent")
    move(client, tenant_id, b["case_number"], "Solved")

    report = client.get(f"/tenants/{tenant_id}/reports/queues").json()
    rows = {r["queue_name"]: r for r in report["rows"]}

    assert [r["queue_name"] for r in report["rows"]] == ["Delivery", "Empty", "General"]
    assert rows["Delivery"]["counts"] == {"WaitingApproval": 1, "Solved": 1}
    assert rows["Delivery"]["open_total"] == 1  # Solved isn't open
    assert rows["Empty"]["counts"] == {} and rows["Empty"]["open_total"] == 0
    assert rows["Empty"]["oldest_open_at"] is None
    assert rows["General"]["counts"] == {"Queued": 1}
    assert report["totals"] == {"WaitingApproval": 1, "Solved": 1, "Queued": 1}
    assert report["open_total"] == 2


def test_queue_report_includes_unrouted_row(client: TestClient, tenant_id: str) -> None:
    client.patch(
        f"/tenants/{tenant_id}/queues/{general_id(client, tenant_id)}", json={"is_active": False}
    )
    new_case(client, tenant_id)
    rows = client.get(f"/tenants/{tenant_id}/reports/queues").json()["rows"]
    unrouted = rows[-1]
    assert (unrouted["queue_id"], unrouted["queue_name"], unrouted["counts"]) == (
        None,
        "Unrouted",
        {"Intake": 1},
    )
    assert next(r for r in rows if r["queue_name"] == "General")["is_active"] is False
