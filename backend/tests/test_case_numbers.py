"""Case numbers: public case IDs as Unix timestamps in microseconds."""

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.services.cases as case_service
from app.domain.ids import JS_MAX_SAFE_INTEGER, MicrosecondIdGenerator
from tests.test_cases_api import CASE_PAYLOAD, create_case


def test_generator_tracks_the_clock_in_microseconds() -> None:
    before = time.time_ns() // 1_000
    value = MicrosecondIdGenerator().next()
    after = time.time_ns() // 1_000
    assert before <= value <= after
    assert len(str(value)) == 16  # microsecond Unix timestamps have 16 digits until 2286
    assert value < JS_MAX_SAFE_INTEGER


def test_generator_never_repeats_within_the_same_microsecond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = 1_790_000_000_000_000_000  # nanoseconds
    monkeypatch.setattr(time, "time_ns", lambda: frozen)
    generator = MicrosecondIdGenerator()
    assert [generator.next() for _ in range(3)] == [
        1_790_000_000_000_000,
        1_790_000_000_000_001,
        1_790_000_000_000_002,
    ]


def test_generator_is_unique_across_threads() -> None:
    generator = MicrosecondIdGenerator()
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        values = [generator.next() for _ in range(500)]
        with lock:
            results.extend(values)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == len(set(results)) == 4000


def test_cases_get_a_timestamp_case_number_and_are_addressed_by_it(
    client: TestClient, tenant_id: str
) -> None:
    before = time.time_ns() // 1_000
    case = create_case(client, tenant_id)
    after = time.time_ns() // 1_000

    assert before <= case["case_number"] <= after
    response = client.get(f"/tenants/{tenant_id}/cases/{case['case_number']}")
    assert response.status_code == 200
    assert response.json()["case_number"] == case["case_number"]

    # The internal UUID is not a valid path id.
    assert client.get(f"/tenants/{tenant_id}/cases/{case['id']}").status_code == 422


def test_case_list_is_newest_first(client: TestClient, tenant_id: str) -> None:
    numbers = [create_case(client, tenant_id)["case_number"] for _ in range(3)]
    listed = [c["case_number"] for c in client.get(f"/tenants/{tenant_id}/cases").json()]
    assert listed == sorted(numbers, reverse=True)


def test_collision_with_another_server_retries_with_a_new_number(
    client: TestClient, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = create_case(client, tenant_id)["case_number"]

    # Simulate another server having already taken the number we'd generate.
    issued: list[int] = []
    sequence = iter([existing, existing + 1_000])

    def fake_next() -> int:
        issued.append(next(sequence))
        return issued[-1]

    monkeypatch.setattr(case_service, "next_case_number", fake_next)

    # A brand-new customer, created in the same transaction just before the case insert.
    payload = {**CASE_PAYLOAD, "customer": {"email": "new.person@example.com"}}
    response = client.post(f"/tenants/{tenant_id}/cases", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["case_number"] == existing + 1_000
    assert issued == [existing, existing + 1_000]
    # The customer created before the failed attempt survived (savepoint rollback only).
    assert body["customer"]["email"] == "new.person@example.com"
    assert len(client.get(f"/tenants/{tenant_id}/cases").json()) == 2
