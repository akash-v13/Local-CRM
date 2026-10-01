"""End to end: intake → enrichment job → worker runs connectors → case routed on the data."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Job
from app.services.enrichment import EnrichmentService
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver
from tests.connector_helpers import create_connector, shop_api
from tests.test_cases_api import CASE_PAYLOAD

RunWorker = Callable[[], int]


@pytest.fixture
def run_worker(session_factory: sessionmaker[Session], fake_apis: FakeApis) -> RunWorker:
    """Process every due job, like the real worker loop. Returns how many ran."""

    def run() -> int:
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=Settings(), resolve=public_resolver
            )
            count = 0
            while run_once(service):
                count += 1
            return count

    return run


def new_case(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/cases", json={**CASE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def get(client: TestClient, tenant_id: str, case: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    return body


def event_types(client: TestClient, tenant_id: str, case: dict[str, Any]) -> list[str]:
    url = f"/tenants/{tenant_id}/cases/{case['case_number']}/events"
    return [e["event_type"] for e in client.get(url).json()]


def vip_queue_for_big_orders(client: TestClient, tenant_id: str) -> None:
    rule = {"conditions": [{"field": "enrichment.shop.orderTotal", "op": "greater_than", "value": "500"}]}
    response = client.post(
        f"/tenants/{tenant_id}/queues",
        json={"name": "High value", "priority": 5, "match_criteria": rule},
    )
    assert response.status_code == 201, response.text


def test_case_is_enriched_then_routed_on_enriched_data(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = shop_api
    create_connector(client, tenant_id)
    vip_queue_for_big_orders(client, tenant_id)

    case = new_case(client, tenant_id)
    assert case["status"] == "Intake"  # waits for enrichment instead of routing straight away
    assert event_types(client, tenant_id, case)[-1] == "enrichment.queued"

    assert run_worker() == 1
    after = get(client, tenant_id, case)
    shop = after["enrichment"]["shop"]
    assert shop["status"] == "ok"
    assert shop["data"]["orderTotal"] == 742.5
    assert shop["connectorName"] == "Shop orders"
    assert "response_json" not in shop  # only mapped fields are stored
    assert (after["status"], after["queue"]["name"]) == ("Queued", "High value")
    assert event_types(client, tenant_id, case)[-3:] == [
        "enrichment.completed",
        "case.routed",
        "case.status_changed",
    ]


def test_later_connectors_use_earlier_results(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = shop_api
    create_connector(client, tenant_id, run_order=1)
    create_connector(
        client,
        tenant_id,
        key="shipping",
        name="Shipping",
        run_order=2,
        url_template="https://shop.example.com/shipments/{{enrichment.shop.trackingNumber}}",
        field_mappings=[{"path": "fault", "target": "fault"}, {"path": "tracking", "target": "tracking"}],
    )
    case = new_case(client, tenant_id)
    run_worker()
    shipping = get(client, tenant_id, case)["enrichment"]["shipping"]
    assert shipping["data"] == {"fault": "carrier", "tracking": "TRK123"}


def test_run_when_skips_non_matching_cases(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = shop_api
    only_email = {"conditions": [{"field": "channel", "op": "equals", "value": "email"}]}
    create_connector(client, tenant_id, run_when=only_email)
    case = new_case(client, tenant_id)  # webform
    run_worker()
    after = get(client, tenant_id, case)
    assert after["enrichment"]["shop"]["status"] == "skipped"
    assert after["status"] == "Queued"  # optional connector skipped: still routed
    assert fake_apis.requests == []


def test_optional_connector_failure_still_routes(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = lambda r: httpx.Response(500)
    create_connector(client, tenant_id)
    case = new_case(client, tenant_id)
    run_worker()
    after = get(client, tenant_id, case)
    assert after["enrichment"]["shop"]["status"] == "failed"
    assert (after["status"], after["queue"]["name"]) == ("Queued", "General")


def test_required_connector_failure_holds_the_case_and_retry_recovers(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = lambda r: httpx.Response(500)
    create_connector(client, tenant_id, required=True)
    case = new_case(client, tenant_id)
    run_worker()
    held = get(client, tenant_id, case)
    assert held["status"] == "EnrichmentFailed"
    assert held["queue"] is None

    # Fix the API, then retry from the UI ("Re-run enrichment").
    fake_apis.handler = shop_api
    url = f"/tenants/{tenant_id}/cases/{case['case_number']}/enrich"
    response = client.post(url, json={"actor_id": "agent.alex"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Intake"
    assert client.post(url, json={}).status_code == 409  # already queued

    run_worker()
    recovered = get(client, tenant_id, case)
    assert recovered["status"] == "Queued"
    assert recovered["enrichment"]["shop"]["status"] == "ok"


def test_re_enriching_a_routed_case_refreshes_data_without_rerouting(
    client: TestClient, tenant_id: str, fake_apis: FakeApis, run_worker: RunWorker
) -> None:
    fake_apis.handler = shop_api
    create_connector(client, tenant_id)
    case = new_case(client, tenant_id)
    run_worker()
    queue_before = get(client, tenant_id, case)["queue"]

    vip_queue_for_big_orders(client, tenant_id)  # a rule that would now match
    client.post(f"/tenants/{tenant_id}/cases/{case['case_number']}/enrich", json={})
    run_worker()
    after = get(client, tenant_id, case)
    assert after["queue"] == queue_before  # refresh only; use "Run routing again" to re-route
    assert after["status"] == "Queued"


def test_no_connectors_means_immediate_routing(client: TestClient, tenant_id: str) -> None:
    case = new_case(client, tenant_id)
    assert case["status"] == "Queued"


def test_unexpected_errors_retry_then_fail_visibly(
    client: TestClient,
    tenant_id: str,
    fake_apis: FakeApis,
    run_worker: RunWorker,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_connector(client, tenant_id)
    case = new_case(client, tenant_id)

    def boom(self: EnrichmentService, job_id: Any) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(EnrichmentService, "enrich_case", boom)

    def make_due() -> None:  # skip the backoff wait
        with session_factory() as session:
            for job in session.scalars(select(Job)).all():
                job.run_after = job.created_at
            session.commit()

    for _ in range(3):  # max_attempts
        run_worker()
        make_due()

    with session_factory() as session:
        job = session.scalars(select(Job)).one()
        assert (job.status, job.attempts) == ("failed", 3)
        assert "database went away" in (job.last_error or "")
    assert get(client, tenant_id, case)["status"] == "EnrichmentFailed"
    assert "enrichment.error" in event_types(client, tenant_id, case)


def test_enrichment_fields_appear_in_the_rule_builder(client: TestClient, tenant_id: str) -> None:
    create_connector(client, tenant_id)
    fields = client.get(f"/tenants/{tenant_id}/routing/fields").json()["fields"]
    labels = {f["key"]: f["label"] for f in fields}
    assert labels["enrichment.shop.orderTotal"] == "Shop orders: Order total"
    assert labels["enrichment.shop.carrier"] == "Shop orders: carrier"
