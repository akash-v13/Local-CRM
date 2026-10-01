"""Glue between database models and the pure routing logic in app/domain/routing.py."""

from typing import Any

from app.domain.routing import QueueCandidate, build_context
from app.models import Case, Queue


def to_candidate(queue: Queue) -> QueueCandidate:
    return QueueCandidate(
        id=queue.id,
        name=queue.name,
        priority=queue.priority,
        created_at=queue.created_at,
        criteria=dict(queue.match_criteria),
    )


def case_context(case: Case, customer_texts: list[str]) -> dict[str, Any]:
    """Everything a routing condition can test, taken from the case."""
    return build_context(
        category=case.category.get("effective"),
        channel=case.channel,
        customer_tier=case.customer.tier,
        messages=customer_texts,
        attributes=dict(case.attributes),
        enrichment=enrichment_data(case),
        queue_name=case.queue.name if case.queue else None,
    )


def enrichment_data(case: Case) -> dict[str, dict[str, Any]]:
    """{connectorKey: {field: value}} for connectors that ran successfully on this case."""
    return {
        key: dict(result.get("data") or {})
        for key, result in case.enrichment.items()
        if isinstance(result, dict) and result.get("status") == "ok"
    }
