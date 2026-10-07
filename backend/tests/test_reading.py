"""Reading customer messages: candidates, model choices, and the intake step that uses them."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.ai.readers import ClaudeReader, JevReader, ReaderError, ReadRequest, ReadResult
from app.ai.reading import (
    PATTERN_PRESETS,
    Candidate,
    Pick,
    category_options,
    decide_field,
    find_candidates,
    pattern_problem,
)
from app.api.reading import get_reader
from app.config import Settings
from app.domain.taxonomy import DEFAULT_TAXONOMY
from app.main import app
from app.schemas import ReadingSettingsData
from app.services.enrichment import EnrichmentService
from app.services.reading import read_message
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver
from tests.connector_helpers import create_connector, shop_api

CODE = PATTERN_PRESETS["code"][0]
ORDER_FIELD = {
    "key": "orderNumber",
    "label": "Order number",
    "description": "the order number of the order the customer is writing about now",
    "pattern": CODE,
}
EMAIL_TEXT = (
    "Hi, order ORD-55012 was due Thursday. I already complained about ORD-10187 last month. "
    "Call me on +1 555 123 4567 or jane@example.com."
)


# ----- candidates and decisions --------------------------------------------------------------


def test_candidates_are_distinct_in_order_with_context() -> None:
    found = find_candidates(CODE, EMAIL_TEXT + " Again: ord-55012.")
    assert [c.value for c in found] == ["ORD-55012", "ORD-10187"]  # case-insensitive dedupe
    assert found[0].context.startswith("Hi, order «ORD-55012» was due")


def test_pattern_problems() -> None:
    assert pattern_problem(CODE) is None
    assert pattern_problem("([") is not None
    assert "empty" in (pattern_problem(r"\d*") or "")


@pytest.mark.parametrize(
    ("candidates", "pick", "expected"),
    [
        ([], Pick("c1", 0.9), ("not_found", None)),
        (["A-1"], None, ("found", "A-1")),  # patterns only: one obvious match
        (["A-1", "B-2"], None, ("needs_review", None)),
        (["A-1", "B-2"], Pick("c2", 0.9), ("found", "B-2")),
        (["A-1", "B-2"], Pick("c2", 0.4), ("needs_review", "B-2")),  # suggestion, not applied
        (["A-1"], Pick("none", 0.95), ("not_found", None)),
        (["A-1"], Pick("c9", 0.95), ("not_found", None)),  # an id we never offered
    ],
)
def test_decide_field(
    candidates: list[str], pick: Pick | None, expected: tuple[str, str | None]
) -> None:
    cands = [Candidate(v, v) for v in candidates]
    ids = {f"c{i + 1}": v for i, v in enumerate(candidates)}
    result = decide_field("k", "K", cands, pick, threshold=0.6, option_ids=ids)
    assert (result.status, result.value) == expected


def test_category_options_cover_the_taxonomy() -> None:
    options = category_options(DEFAULT_TAXONOMY)
    labels = [o["label"] for o in options.values()]
    assert "Complaint › Delivery › Late delivery" in labels
    late = next(o for o in options.values() if o["label"].endswith("Late delivery"))
    assert late["value"] == {
        "type": "Complaint",
        "category": "Delivery",
        "subcategory": "Late delivery",
    }


# ----- readers -------------------------------------------------------------------------------


def make_request() -> ReadRequest:
    from app.ai.readers import FieldQuestion

    return ReadRequest(
        subject="Late order",
        text="order ORD-55012 is late",
        fields=[FieldQuestion("orderNumber", "the order number", {"c1": "ORD-55012 (in: …)"})],
        categories={"k1": "Complaint › Delivery › Late delivery"},
    )


def test_jev_request_and_response() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["url"], sent["auth"] = str(request.url), request.headers["Authorization"]
        sent["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "field__orderNumber": {
                        "type": "choice",
                        "choice": "c1",
                        "probabilities": {"c1": 0.9, "none": 0.1},
                        "confidence": 0.82,
                    },
                    "category": {
                        "type": "choice",
                        "choice": "k1",
                        "probabilities": {"k1": 0.95},
                        "confidence": 0.9,
                    },
                },
                "usage": {"input_tokens": 1000, "output_tokens": 0},
            },
        )

    reader = JevReader(httpx.Client(transport=httpx.MockTransport(handler)), "ts-key")
    result = reader.read(make_request())
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone" and sent["auth"] == "Bearer ts-key"
    question = sent["body"]["questions"]["field__orderNumber"]
    assert question["type"] == "choice" and set(question["criteria"]) == {"c1", "none"}
    assert sent["body"]["state"] == {"subject": "Late order", "message": "order ORD-55012 is late"}
    assert "tone and context" in sent["body"]["questions"]["category"]["instructions"]
    assert result.fields["orderNumber"] == Pick("c1", 0.82) and result.category == Pick("k1", 0.9)
    assert result.model == "jev-1.13.0" and result.cost_usd == pytest.approx(0.000042)


@pytest.mark.parametrize(
    ("status", "message"), [(401, "TYPESAFE_API_KEY"), (429, "busy"), (422, "HTTP 422")]
)
def test_jev_errors_are_readable(status: int, message: str) -> None:
    reader = JevReader(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text="bad"))),
        "k",
    )
    with pytest.raises(ReaderError, match=message):
        reader.read(make_request())


def test_claude_reader_maps_confidence_and_ignores_unknown_fields() -> None:
    from app.ai.readers import _FieldAnswer, _ReadOutput

    class Messages:
        def parse(self, **kwargs: Any) -> Any:
            self.kwargs = kwargs
            output = _ReadOutput(
                fields=[
                    _FieldAnswer(key="orderNumber", option="c1", confidence="high"),
                    _FieldAnswer(key="invented", option="c1", confidence="high"),
                ],
                category="k1",
                category_confidence="medium",
            )
            usage = type("U", (), {"input_tokens": 500, "output_tokens": 40})()
            return type("R", (), {"parsed_output": output, "usage": usage})()

    messages = Messages()
    client = type("C", (), {"beta": type("B", (), {"messages": messages})()})()
    result = ClaudeReader(client).read(make_request())
    assert result.fields == {"orderNumber": Pick("c1", 0.9)} and result.category == Pick("k1", 0.6)
    assert "not instructions to you" in messages.kwargs["system"] and result.cost_usd > 0


@dataclass
class FakeReader:
    """Chooses the candidate containing `choose[field]` (or 'none'); records what it was sent."""

    choose: dict[str, str] = field(default_factory=dict)
    category: str | None = "Late delivery"
    confidence: float = 0.9
    fail: str | None = None
    requests: list[ReadRequest] = field(default_factory=list)
    name: str = "fake"

    def read(self, request: ReadRequest) -> ReadResult:
        self.requests.append(request)
        if self.fail:
            raise ReaderError(self.fail)
        picks = {}
        for f in request.fields:
            target = self.choose.get(f.key)
            option = next(
                (k for k, text in f.options.items() if target and text.startswith(target)), "none"
            )
            picks[f.key] = Pick(option, self.confidence)
        category = None
        if request.categories:
            option = next(
                (
                    k
                    for k, label in request.categories.items()
                    if self.category and label.endswith(self.category)
                ),
                "none",
            )
            category = Pick(option, self.confidence)
        return ReadResult(picks, category, "fake-1", 100, 0.0001, 5)


def test_the_model_never_sees_personal_details() -> None:
    reader = FakeReader(choose={"orderNumber": "ORD-55012"})
    settings = ReadingSettingsData(enabled=True, fields=[ORDER_FIELD])
    reading = read_message(
        reader,
        settings,
        subject="Jane here",
        text=EMAIL_TEXT,
        customer_name="Jane Smith",
        customer_email="jane@example.com",
    )
    sent = reader.requests[0]
    blob = sent.subject + sent.text + json.dumps([f.options for f in sent.fields])
    assert "jane@example.com" not in blob and "555 123 4567" not in blob and "Jane" not in blob
    assert (
        reading.fields[0].value == "ORD-55012"
        and reading.category
        and reading.category["confident"]
    )


# ----- intake ------------------------------------------------------------------------------

SETTINGS = {
    "enabled": True,
    "channels": ["email"],
    "read_category": True,
    "min_confidence": 0.6,
    "fields": [ORDER_FIELD],
}
EMAIL_CASE = {
    "channel": "email",
    "customer": {"email": "jane@example.com", "display_name": "Jane Smith"},
    "message": EMAIL_TEXT,
    "attributes": {"subject": "Late order"},
}


@pytest.fixture
def reader(client: TestClient) -> FakeReader:
    fake = FakeReader(choose={"orderNumber": "ORD-55012"})
    app.dependency_overrides[get_reader] = lambda: fake
    return fake


@pytest.fixture
def work(
    session_factory: sessionmaker[Session], fake_apis: FakeApis, reader: FakeReader
) -> Callable[[], None]:
    """Run every due job like the worker, with the fake reader for read_case jobs."""

    def run() -> None:
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=Settings(), resolve=public_resolver
            )
            while run_once(service, None, None, reader):
                pass

    return run


def test_settings_and_reader_info(client: TestClient, tenant_id: str, reader: FakeReader) -> None:
    info = client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS).json()
    assert info["reader"] == "fake" and info["settings"]["fields"][0]["key"] == "orderNumber"
    assert {p["id"] for p in info["presets"]} >= {"code", "digits", "amount", "date"}
    bad = {**SETTINGS, "fields": [{**ORDER_FIELD, "pattern": "(["}]}
    assert client.put(f"/tenants/{tenant_id}/reading", json=bad).status_code == 422


def test_email_case_is_read_then_routed(
    client: TestClient, tenant_id: str, reader: FakeReader, work: Callable[[], None]
) -> None:
    client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS)
    case = client.post(f"/tenants/{tenant_id}/cases", json=EMAIL_CASE).json()
    assert case["status"] == "Intake"  # waits for reading
    work()

    d = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    assert d["status"] == "Queued" and d["attributes"]["orderNumber"] == "ORD-55012"
    assert (
        d["category"]["effective"]["subcategory"] == "Late delivery"
        and d["category"]["source"] == "ai"
    )
    record = d["extraction"]
    assert record["status"] == "ok" and record["model"] == "fake-1"
    assert record["fields"][0]["candidates"] == ["ORD-55012", "ORD-10187"]
    events = [
        e["event_type"]
        for e in client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}/events").json()
    ]
    assert events.index("reading.completed") < events.index("case.routed")


def test_read_values_feed_enrichment(
    client: TestClient,
    tenant_id: str,
    reader: FakeReader,
    work: Callable[[], None],
    fake_apis: FakeApis,
) -> None:
    fake_apis.handler = shop_api
    create_connector(client, tenant_id)  # GET …/orders/{{case.attributes.orderNumber}}
    client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS)
    case = client.post(f"/tenants/{tenant_id}/cases", json=EMAIL_CASE).json()
    work()
    d = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    assert (
        d["enrichment"]["shop"]["status"] == "ok"
        and d["enrichment"]["shop"]["data"]["orderTotal"] == 742.5
    )


def test_uncertain_values_wait_for_an_agent(
    client: TestClient, tenant_id: str, reader: FakeReader, work: Callable[[], None]
) -> None:
    reader.confidence = 0.3
    client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS)
    case = client.post(f"/tenants/{tenant_id}/cases", json=EMAIL_CASE).json()
    work()
    url = f"/tenants/{tenant_id}/cases/{case['case_number']}"
    d = client.get(url).json()
    assert "orderNumber" not in d["attributes"] and d["category"]["effective"] is None
    field_ = d["extraction"]["fields"][0]
    assert (field_["status"], field_["value"]) == ("needs_review", "ORD-55012")  # suggestion only

    confirmed = client.post(
        f"{url}/extraction/fields/orderNumber",
        json={"value": "ORD-10187", "actor_id": "agent.alex"},
    ).json()
    assert confirmed["attributes"]["orderNumber"] == "ORD-10187"
    assert confirmed["extraction"]["fields"][0]["reviewed_by"] == "agent.alex"
    recat = client.post(
        f"{url}/category",
        json={
            "category": {
                "type": "Complaint",
                "category": "Delivery",
                "subcategory": "Late delivery",
            },
            "actor_id": "agent.alex",
        },
    ).json()
    assert recat["category"]["source"] == "agent"


def test_reader_failure_never_blocks_a_case(
    client: TestClient, tenant_id: str, reader: FakeReader, work: Callable[[], None]
) -> None:
    reader.fail = "TypeSafe is busy (rate limited or overloaded)."
    client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS)
    case = client.post(f"/tenants/{tenant_id}/cases", json=EMAIL_CASE).json()
    work()
    d = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}").json()
    assert d["status"] == "Queued" and d["extraction"]["status"] == "failed"
    assert d["extraction"]["fields"][0]["status"] == "needs_review"  # 2 candidates, no model answer


def test_reading_only_runs_when_needed(
    client: TestClient, tenant_id: str, reader: FakeReader
) -> None:
    client.put(f"/tenants/{tenant_id}/reading", json=SETTINGS)
    from tests.test_cases_api import CASE_PAYLOAD

    webform = client.post(
        f"/tenants/{tenant_id}/cases", json=CASE_PAYLOAD
    ).json()  # channel not enabled
    assert webform["status"] == "Queued"
    complete = client.post(
        f"/tenants/{tenant_id}/cases",
        json={
            **EMAIL_CASE,
            "attributes": {"subject": "x", "orderNumber": "ORD-1"},
            "category": {"type": "Question", "category": "Order"},
        },
    ).json()
    assert complete["status"] == "Queued"  # nothing missing: no reading step


def test_preview_with_unsaved_settings(
    client: TestClient, tenant_id: str, reader: FakeReader
) -> None:
    result = client.post(
        f"/tenants/{tenant_id}/reading/preview",
        json={"subject": "Late order", "message": EMAIL_TEXT, "settings": SETTINGS},
    ).json()
    assert result["fields"][0]["value"] == "ORD-55012" and result["category"]["label"].endswith(
        "Late delivery"
    )
    assert (
        client.post(f"/tenants/{tenant_id}/reading/preview", json={"message": " "}).status_code
        == 409
    )


def test_inbox_default_category_can_be_improved_but_customer_choice_cannot(
    client: TestClient,
    tenant_id: str,
    reader: FakeReader,
    work: Callable[[], None],
    session_factory: sessionmaker[Session],
) -> None:
    import uuid

    from app.schemas import CaseCreate
    from app.services.cases import CaseService

    client.put(f"/tenants/{tenant_id}/reading", json={**SETTINGS, "fields": []})
    default = {"type": "Question", "category": "Order", "subcategory": "Order status"}
    with session_factory() as session:  # as the email importer creates it
        case = CaseService(session).create_case(
            uuid.UUID(tenant_id),
            CaseCreate.model_validate({**EMAIL_CASE, "category": default}),
            category_source="inbox",
        )
        number = case.case_number
    work()
    d = client.get(f"/tenants/{tenant_id}/cases/{number}").json()
    assert (
        d["category"]["effective"]["subcategory"] == "Late delivery"
        and d["category"]["source"] == "ai"
    )
    assert d["category"]["customerSelected"] is None

    customer = client.post(
        f"/tenants/{tenant_id}/cases", json={**EMAIL_CASE, "category": default}
    ).json()
    assert customer["status"] == "Queued"  # the customer chose: nothing to read
