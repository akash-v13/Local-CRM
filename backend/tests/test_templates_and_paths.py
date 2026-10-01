"""Unit tests for {{placeholder}} templates and JSON path extraction."""

import pytest

from app.domain.jsonpath import extract
from app.domain.templates import MissingTemplateValue, placeholders, render

CTX = {
    "case": {
        "attributes": {"orderNumber": "ORD/1 2?x", "count": 3},
        "customer": {"email": "a@b.co"},
    },
    "enrichment": {"shop": {"note": 'He said "hi"\nbye'}},
}


def test_extract_dicts_and_lists() -> None:
    data = {"order": {"items": [{"sku": "A1"}, {"sku": "B2"}], "total": 0}}
    assert extract(data, "order.items.1.sku") == (True, "B2")
    assert extract(data, "order.total") == (True, 0)  # falsy values are still "found"
    assert extract(data, "order.items.5.sku") == (False, None)
    assert extract(data, "order.missing") == (False, None)
    assert extract(data, "order.items.sku") == (False, None)


def test_placeholders_listed() -> None:
    assert placeholders("x/{{ case.a }}/{{enrichment.b.c}}") == ["case.a", "enrichment.b.c"]


def test_url_values_are_percent_encoded() -> None:
    url = render(
        "https://x/orders/{{case.attributes.orderNumber}}?n={{case.attributes.count}}", CTX, "url"
    )
    assert url == "https://x/orders/ORD%2F1%202%3Fx?n=3"


def test_header_values_cannot_inject_new_lines() -> None:
    assert "\n" not in render("{{enrichment.shop.note}}", CTX, "header")


def test_json_values_cannot_break_out_of_strings() -> None:
    body = render('{"note": "{{enrichment.shop.note}}"}', CTX, "json")
    import json

    assert json.loads(body) == {"note": 'He said "hi"\nbye'}


def test_missing_or_empty_values_raise() -> None:
    with pytest.raises(MissingTemplateValue) as exc:
        render("{{case.attributes.nope}}", CTX, "url")
    assert exc.value.path == "case.attributes.nope"
    with pytest.raises(MissingTemplateValue):
        render("{{case.attributes.empty}}", {"case": {"attributes": {"empty": ""}}}, "url")
