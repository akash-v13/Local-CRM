"""Building the data a connector sees from a case."""

from typing import Any

from app.domain.routing import build_context
from app.domain.templates import build_template_context
from app.models import Case
from app.services.routing import enrichment_data


def contexts_for(
    case: Case, customer_texts: list[str], enrichment: dict[str, dict[str, Any]] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(template context for {{placeholders}}, routing context for 'run when').

    `enrichment` overrides the case's stored enrichment data (the worker passes
    the results gathered so far in the current run).
    """
    data = enrichment_data(case) if enrichment is None else enrichment
    effective = case.category.get("effective")
    template = build_template_context(
        case_number=case.case_number,
        channel=case.channel,
        language=case.language,
        category=effective,
        customer={
            "email": case.customer.email,
            "display_name": case.customer.display_name,
            "tier": case.customer.tier,
        },
        attributes=dict(case.attributes),
        enrichment=data,
    )
    routing = build_context(
        category=effective,
        channel=case.channel,
        customer_tier=case.customer.tier,
        messages=customer_texts,
        attributes=dict(case.attributes),
        enrichment=data,
    )
    return template, routing
