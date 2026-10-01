"""The data prompt templates can use, built from a case (or a test-lab sample).

Every string in the context is masked first (app/ai/pii.py), so templates
only ever see placeholders such as [CUSTOMER_NAME], never real personal data.
Variable reference: app/ai/templates/README.md.
"""

from dataclasses import dataclass, field
from typing import Any

from app.ai.pii import Masker


@dataclass(frozen=True)
class DraftInput:
    """Everything about one case (or sample) a prompt may use. Not yet masked."""

    reference: str  # "Case 1790…" or "Sample: …"
    case_number: int | None
    channel: str
    category: dict[str, Any] | None
    queue_name: str | None
    customer_name: str | None
    customer_email: str | None
    customer_tier: str | None
    attributes: dict[str, Any]
    # connector key → {field: value}, for connectors that ran successfully
    enrichment: dict[str, dict[str, Any]]
    # connector key → display name (for the facts block)
    enrichment_labels: dict[str, str] = field(default_factory=dict)
    # (who, text) oldest first; who is "customer" or "agent". Customer-visible only.
    thread: list[tuple[str, str]] = field(default_factory=list)
    compensation: str | None = None  # from the compensation matrix, when it exists


def category_label(category: dict[str, Any] | None) -> str:
    if not category:
        return "Uncategorized"
    return " › ".join(
        str(category[k]) for k in ("type", "category", "subcategory") if category.get(k)
    )


def _mask(value: Any, masker: Masker) -> Any:
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, dict):
        return {k: _mask(v, masker) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, masker) for v in value]
    return value


def build_context(business_name: str, draft: DraftInput, masker: Masker) -> dict[str, Any]:
    category = draft.category or {}
    customer_lines = [text for who, text in draft.thread if who == "customer"]
    has_name = bool(draft.customer_name and draft.customer_name.strip())
    first_name = masker.first_name_placeholder if has_name else None
    return {
        "business": {"name": business_name},
        "case": {
            "reference": draft.reference,
            "number": draft.case_number,
            "channel": draft.channel,
            "type": category.get("type"),
            "category": category.get("category"),
            "subcategory": category.get("subcategory"),
            "category_label": category_label(draft.category),
            "queue": draft.queue_name,
            "attributes": _mask(dict(draft.attributes), masker),
        },
        "customer": {
            "name": "[CUSTOMER_NAME]" if has_name else None,
            "first_name": first_name,
            "tier": draft.customer_tier,
        },
        "enrichment": _mask(draft.enrichment, masker),
        "enrichment_sources": _mask(
            {draft.enrichment_labels.get(k, k): v for k, v in draft.enrichment.items() if v}, masker
        ),
        "decisions": {"compensation": draft.compensation},
        "thread": [{"from": who, "text": masker.mask(text)} for who, text in draft.thread],
        "latest_message": masker.mask(customer_lines[-1]) if customer_lines else "",
    }
