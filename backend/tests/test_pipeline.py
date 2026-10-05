"""Intake pipeline: the business-wide definition and per-case executions."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FakeApis
from tests.connector_helpers import create_connector, shop_api
from tests.test_enrichment import RunWorker, new_case, run_worker  # noqa: F401

SHIPPING = {
    "key": "shipping",
    "name": "Shipping tracker",
    "run_order": 200,
    "max_retries": 0,
    "url_template": "https://shop.example.com/shipments/{{enrichment.shop.trackingNumber}}",
    "field_mappings": [{"path": "fault", "target": "fault"}],
}


def pipeline(client: TestClient, tenant_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/tenants/{tenant_id}/pipeline").json()
    return result


def test_definition_shows_steps_in_order_with_dependencies(
    client: TestClient, tenant_id: str
) -> None:
    create_connector(client, tenant_id)  # "shop", run order 100
    create_connector(client, tenant_id, **SHIPPING)
    client.post(
        f"/tenants/{tenant_id}/compensation/rules",
        json={
            "name": "Refund",
            "priority": 1,
            "outcome": {"type": "refund", "amount": 10, "requires_approval": True},
        },
    )

    d = pipeline(client, tenant_id)
    shop, shipping = d["connectors"]
    assert (shop["position"], shop["name"], shop["credential_name"]) == (
        1,
        "Shop orders",
        "Shop API key",
    )
    assert shop["uses"] == [
        {"source": "case", "path": "case.attributes.orderNumber", "step_key": None, "field": None}
    ]
    assert (
        shipping["uses"][0]["step_key"] == "shop"
        and shipping["uses"][0]["field"] == "trackingNumber"
    )
    assert shop["problems"] == [] and shipping["problems"] == []
    assert [q["name"] for q in d["queues"]] == ["General"]
    assert d["compensation_rules"][0]["outcome"] == "Refund: 10.0, always needs approval"
    assert "90 days" in d["compensation_guardrails"]


def test_definition_flags_steps_that_cant_work(client: TestClient, tenant_id: str) -> None:
    create_connector(client, tenant_id, run_order=300)  # shop now runs AFTER shipping
    create_connector(
        client,
        tenant_id,
        **{
            **SHIPPING,
            "url_template": "https://shop.example.com/s/{{enrichment.shop.trackingNumber}}/{{enrichment.shop.nope}}"
            "/{{enrichment.gone.x}}",
        },
    )
    shipping = pipeline(client, tenant_id)["connectors"][0]
    assert shipping["name"] == "Shipping tracker"
    problems = " | ".join(shipping["problems"])
    assert "Shop orders runs after this step (step 2)" in problems
    assert "'gone' is not a connector" in problems


def test_executions_show_each_case_run(
    client: TestClient,
    tenant_id: str,
    fake_apis: FakeApis,
    run_worker: RunWorker,  # noqa: F811
) -> None:
    fake_apis.handler = shop_api
    create_connector(client, tenant_id)
    ok_case = new_case(client, tenant_id)  # ORD-55012: the fake shop knows it
    bad_case = new_case(client, tenant_id, attributes={"orderNumber": "ORD-404"})

    pending = client.get(f"/tenants/{tenant_id}/pipeline/executions").json()
    assert {e["outcome"] for e in pending} == {"in_progress"}
    run_worker()
    create_connector(client, tenant_id, **SHIPPING)  # added after these cases ran

    rows = {
        e["case_number"]: e for e in client.get(f"/tenants/{tenant_id}/pipeline/executions").json()
    }
    good, bad = rows[ok_case["case_number"]], rows[bad_case["case_number"]]
    assert [(s["name"], s["status"]) for s in good["steps"]] == [
        ("Shop orders", "ok"),
        ("Shipping tracker", "not_run"),
    ]
    assert good["outcome"] == "ok" and good["queue_name"] == "General"
    assert good["steps"][0]["request"] is None  # details only on the detail view
    assert bad["outcome"] == "failed" and bad["steps"][0]["http_status"] == 404

    failed_only = client.get(
        f"/tenants/{tenant_id}/pipeline/executions", params={"outcome": "failed"}
    ).json()
    assert [e["case_number"] for e in failed_only] == [bad_case["case_number"]]

    detail = client.get(f"/tenants/{tenant_id}/pipeline/executions/{ok_case['case_number']}").json()
    step = detail["steps"][0]
    assert step["data"]["orderTotal"] == 742.5 and step["request"]["url"].endswith(
        "/orders/ORD-55012"
    )
    assert "super-secret-key" not in str(step["request"])  # secrets never shown
    assert detail["routing"]["queue_name"] == "General" and detail["routing"]["routed_at"]
    assert detail["enriched_at"] is not None
    assert client.get(f"/tenants/{tenant_id}/pipeline/executions/1").status_code == 404
