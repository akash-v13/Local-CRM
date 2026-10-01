"""Queue matching: which queue should a case go to?

The design (Idea 7 in docs/04-product-ideas.md) combines two patterns:

- **Decision list:** active queues are checked in priority order (lower
  number first; ties broken by creation time). The FIRST queue whose criteria
  match wins. A queue with no conditions matches everything, so a catch-all
  queue with a high priority number acts as the fallback.
- **Specification:** a queue's criteria are small conditions combined with
  "all" (AND) or "any" (OR).

Criteria are stored on the queue as JSON:

    {"match": "all",
     "conditions": [
        {"field": "category.category", "op": "equals",       "value": "Delivery"},
        {"field": "message",           "op": "contains_any", "value": ["late", "delayed"]}
     ]}

Everything here is pure Python (no database), so it is fast to unit-test and
the same logic powers real routing and the Operations Portal's preview.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

Operator = Literal["equals", "not_equals", "one_of", "contains_any", "greater_than", "less_than"]

# Fields a condition can test. `attributes.<key>` (tenant custom fields) is also allowed.
FIELDS: dict[str, str] = {
    "category.type": "Case type",
    "category.category": "Category",
    "category.subcategory": "Subcategory",
    "channel": "Channel",
    "customer.tier": "Customer tier",
    "queue.name": "Queue",
    "message": "Customer message text",
}
ATTRIBUTE_PREFIX = "attributes."
# Data fetched by connectors: "enrichment.<connectorKey>.<field>", e.g. enrichment.shop.orderTotal
ENRICHMENT_PREFIX = "enrichment."

OPERATORS: dict[Operator, str] = {
    "equals": "is",
    "not_equals": "is not",
    "one_of": "is one of",
    "contains_any": "contains any of the words",
    "greater_than": "is greater than",
    "less_than": "is less than",
}
NUMERIC_OPERATORS: frozenset[Operator] = frozenset({"greater_than", "less_than"})
LIST_OPERATORS: frozenset[Operator] = frozenset({"one_of", "contains_any"})


def is_known_field(name: str) -> bool:
    if name in FIELDS:
        return True
    if name.startswith(ATTRIBUTE_PREFIX):
        return len(name) > len(ATTRIBUTE_PREFIX)
    if name.startswith(ENRICHMENT_PREFIX):
        parts = name[len(ENRICHMENT_PREFIX) :].split(".")
        return len(parts) == 2 and all(parts)
    return False


def to_number(value: Any) -> float | None:
    """Parse numbers like 42, "42", "1,250.50" or "$19.99"; None if it isn't one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    cleaned = str(value).strip().replace(",", "").lstrip("$€£")
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_context(
    *,
    category: dict[str, Any] | None,
    channel: str,
    customer_tier: str | None,
    messages: Sequence[str],
    attributes: dict[str, Any],
    enrichment: dict[str, dict[str, Any]] | None = None,
    queue_name: str | None = None,
) -> dict[str, Any]:
    """Flatten a case into the {field: value} shape that conditions test against.

    `category` is the case's *effective* category. `messages` are the customer's
    own messages (joined for keyword matching). `enrichment` is
    {connectorKey: {field: value}} for connectors that succeeded.
    """
    category = category or {}
    context: dict[str, Any] = {
        "category.type": category.get("type"),
        "category.category": category.get("category"),
        "category.subcategory": category.get("subcategory"),
        "channel": channel,
        "customer.tier": customer_tier,
        "message": "\n".join(messages),
        "queue.name": queue_name,
    }
    for key, value in attributes.items():
        context[ATTRIBUTE_PREFIX + key] = value
    for connector_key, fields in (enrichment or {}).items():
        for field_name, value in fields.items():
            context[f"{ENRICHMENT_PREFIX}{connector_key}.{field_name}"] = value
    return context


@dataclass(frozen=True)
class ConditionResult:
    field: str
    op: str
    value: Any
    matched: bool
    actual: Any  # what the case had (for contains_any: the words that were found)


@dataclass(frozen=True)
class QueueCandidate:
    """The parts of a queue routing needs. Decoupled from the database model."""

    id: UUID | None  # None for an unsaved draft being previewed
    name: str
    priority: int
    created_at: datetime
    criteria: dict[str, Any]


@dataclass(frozen=True)
class QueueEvaluation:
    queue: QueueCandidate
    matched: bool
    conditions: list[ConditionResult] = field(default_factory=list)


@dataclass(frozen=True)
class RoutingResult:
    winner: QueueCandidate | None
    # Every candidate in the order it was checked, including those after the winner,
    # so the preview can show why each queue did or didn't match.
    evaluations: list[QueueEvaluation]


def _norm(value: Any) -> str:
    return str(value).strip().casefold()


def _find_words(text: str, words: Sequence[str]) -> list[str]:
    """Whole-word, case-insensitive matches: 'late' matches 'Late!' but not 'template'.

    Uses "not preceded/followed by a letter or digit" rather than `\\b`, so keywords
    that start or end with a symbol (e.g. "$50") still match.
    """
    return [
        w
        for w in words
        if w.strip() and re.search(rf"(?<!\w){re.escape(w.strip())}(?!\w)", text, re.I)
    ]


def evaluate_condition(condition: dict[str, Any], context: dict[str, Any]) -> ConditionResult:
    name, op, expected = condition["field"], condition["op"], condition["value"]
    actual = context.get(name)
    present = actual is not None and _norm(actual) != ""

    if op == "equals":
        matched = present and _norm(actual) == _norm(expected)
    elif op == "not_equals":
        matched = not present or _norm(actual) != _norm(expected)
    elif op == "one_of":
        matched = present and _norm(actual) in {_norm(v) for v in expected}
    elif op == "contains_any":
        found = _find_words(str(actual), expected) if present else []
        return ConditionResult(name, op, expected, bool(found), found)
    elif op in NUMERIC_OPERATORS:
        number, limit = to_number(actual), to_number(expected)
        if number is None or limit is None:
            matched = False
        else:
            matched = number > limit if op == "greater_than" else number < limit
    else:
        raise ValueError(f"Unknown operator: {op}")

    return ConditionResult(name, op, expected, matched, actual)


def evaluate_criteria(
    criteria: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, list[ConditionResult]]:
    """Evaluate every condition (not short-circuited, so the preview can explain all of them)."""
    conditions = criteria.get("conditions") or []
    if not conditions:
        return True, []  # no conditions = catch-all
    results = [evaluate_condition(c, context) for c in conditions]
    combine = any if criteria.get("match") == "any" else all
    return combine(r.matched for r in results), results


def route(candidates: Sequence[QueueCandidate], context: dict[str, Any]) -> RoutingResult:
    """Check queues in priority order; the first match wins."""
    ordered = sorted(candidates, key=lambda q: (q.priority, q.created_at))
    evaluations: list[QueueEvaluation] = []
    winner: QueueCandidate | None = None
    for queue in ordered:
        matched, results = evaluate_criteria(queue.criteria, context)
        evaluations.append(QueueEvaluation(queue, matched, results))
        if matched and winner is None:
            winner = queue
    return RoutingResult(winner, evaluations)


def describe_condition(result: ConditionResult) -> str:
    """Human-readable, e.g. 'Category is "Delivery"'."""
    label = FIELDS.get(result.field) or (
        result.field.removeprefix(ATTRIBUTE_PREFIX).removeprefix(ENRICHMENT_PREFIX)
    )
    value = ", ".join(result.value) if isinstance(result.value, list) else result.value
    return f'{label} {OPERATORS.get(result.op, result.op)} "{value}"'  # type: ignore[call-overload]
