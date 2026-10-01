"""Unit tests for queue matching (no database)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.routing import (
    QueueCandidate,
    build_context,
    evaluate_condition,
    evaluate_criteria,
    is_known_field,
    route,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)

CONTEXT = build_context(
    category={"type": "Complaint", "category": "Delivery", "subcategory": "Late delivery"},
    channel="webform",
    customer_tier="Gold",
    messages=["My order arrived LATE.", "Still no refund!"],
    attributes={"orderNumber": "ORD-1", "region": "EU"},
)


def cond(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"field": field, "op": op, "value": value}


def queue(
    name: str, priority: int, conditions: list[dict[str, Any]], match: str = "all", age: int = 0
) -> QueueCandidate:
    return QueueCandidate(
        id=None,
        name=name,
        priority=priority,
        created_at=T0 + timedelta(minutes=age),
        criteria={"match": match, "conditions": conditions},
    )


class TestConditions:
    def test_equals_is_case_and_whitespace_insensitive(self) -> None:
        assert evaluate_condition(
            cond("category.category", "equals", " delivery "), CONTEXT
        ).matched
        assert not evaluate_condition(cond("category.category", "equals", "Order"), CONTEXT).matched

    def test_not_equals_matches_missing_values(self) -> None:
        assert evaluate_condition(cond("attributes.missing", "not_equals", "x"), CONTEXT).matched
        assert not evaluate_condition(cond("channel", "not_equals", "WEBFORM"), CONTEXT).matched

    def test_one_of(self) -> None:
        assert evaluate_condition(
            cond("customer.tier", "one_of", ["gold", "platinum"]), CONTEXT
        ).matched
        assert not evaluate_condition(cond("customer.tier", "one_of", ["silver"]), CONTEXT).matched

    def test_contains_any_matches_whole_words_and_reports_them(self) -> None:
        result = evaluate_condition(
            cond("message", "contains_any", ["late", "refund", "bomb"]), CONTEXT
        )
        assert result.matched
        assert result.actual == ["late", "refund"]
        # 'late' must not match inside another word
        ctx = {**CONTEXT, "message": "Use the template please"}
        assert not evaluate_condition(cond("message", "contains_any", ["late"]), ctx).matched

    def test_keywords_with_symbols_match_literally(self) -> None:
        ctx = {**CONTEXT, "message": "charged $50 (twice)"}
        assert evaluate_condition(cond("message", "contains_any", ["$50"]), ctx).matched
        assert evaluate_condition(cond("message", "contains_any", ["(twice)"]), ctx).matched
        assert not evaluate_condition(cond("message", "contains_any", ["$5"]), ctx).matched

    def test_attribute_fields(self) -> None:
        assert evaluate_condition(cond("attributes.region", "equals", "eu"), CONTEXT).matched

    def test_missing_values_never_equal(self) -> None:
        assert not evaluate_condition(cond("attributes.nope", "equals", ""), CONTEXT).matched
        assert not evaluate_condition(cond("attributes.nope", "one_of", ["x"]), CONTEXT).matched


class TestCriteria:
    def test_no_conditions_is_catch_all(self) -> None:
        assert evaluate_criteria({"match": "all", "conditions": []}, CONTEXT) == (True, [])

    def test_all_vs_any(self) -> None:
        conditions = [cond("channel", "equals", "webform"), cond("channel", "equals", "email")]
        assert not evaluate_criteria({"match": "all", "conditions": conditions}, CONTEXT)[0]
        assert evaluate_criteria({"match": "any", "conditions": conditions}, CONTEXT)[0]

    def test_every_condition_is_explained(self) -> None:
        conditions = [cond("channel", "equals", "email"), cond("customer.tier", "equals", "Gold")]
        matched, results = evaluate_criteria({"match": "all", "conditions": conditions}, CONTEXT)
        assert not matched
        assert [r.matched for r in results] == [False, True]


class TestRoute:
    def test_first_match_by_priority_wins(self) -> None:
        general = queue("General", 1000, [])
        delivery = queue("Delivery", 20, [cond("category.category", "equals", "Delivery")])
        vip = queue("VIP", 10, [cond("customer.tier", "equals", "Platinum")])
        result = route([general, delivery, vip], CONTEXT)

        assert result.winner == delivery
        assert [e.queue.name for e in result.evaluations] == ["VIP", "Delivery", "General"]
        assert [e.matched for e in result.evaluations] == [False, True, True]

    def test_ties_broken_by_creation_time(self) -> None:
        older = queue("Older", 10, [], age=0)
        newer = queue("Newer", 10, [], age=5)
        assert route([newer, older], CONTEXT).winner == older

    def test_no_match_returns_none(self) -> None:
        only = queue("Email only", 10, [cond("channel", "equals", "email")])
        assert route([only], CONTEXT).winner is None
        assert route([], CONTEXT).winner is None


def test_known_fields() -> None:
    assert is_known_field("category.category")
    assert is_known_field("attributes.orderNumber")
    assert not is_known_field("attributes.")
    assert not is_known_field("customer.email")
