"""`{{placeholder}}` templates for connector requests.

A connector's URL, headers and body can reference case data:

    https://shop.example.com/orders/{{case.attributes.orderNumber}}
    {"email": "{{case.customer.email}}", "tracking": "{{enrichment.shop.trackingNumber}}"}

Placeholders are dotted paths into the template context (see
`build_template_context`). Values are escaped for where they're inserted, so
case data can never break out of its slot:

- "url":    percent-encoded (a "/" or "?" in an order number can't change the path)
- "header": newlines removed (no header injection)
- "json":   JSON-string escaped (quotes can't end the string)
"""

import json
import re
from typing import Any, Literal
from urllib.parse import quote

from app.domain.jsonpath import extract

Mode = Literal["url", "header", "json", "raw"]

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


class MissingTemplateValue(Exception):
    """A placeholder refers to data the case doesn't have (e.g. no order number)."""

    def __init__(self, path: str) -> None:
        super().__init__(f"No value for {{{{{path}}}}}")
        self.path = path


def placeholders(template: str) -> list[str]:
    return [m.group(1) for m in PLACEHOLDER.finditer(template)]


def _escape(value: Any, mode: Mode) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    if mode == "url":
        return quote(text, safe="")
    if mode == "header":
        return text.replace("\r", " ").replace("\n", " ")
    if mode == "json":
        return json.dumps(text)[1:-1]
    return text


def render(template: str, context: dict[str, Any], mode: Mode) -> str:
    """Replace every {{path}}; raise MissingTemplateValue if any path is absent or empty."""

    def substitute(match: re.Match[str]) -> str:
        path = match.group(1)
        found, value = extract(context, path)
        if not found or value is None or value == "":
            raise MissingTemplateValue(path)
        return _escape(value, mode)

    return PLACEHOLDER.sub(substitute, template)


def build_template_context(
    *,
    case_number: int,
    channel: str,
    language: str,
    category: dict[str, Any] | None,
    customer: dict[str, Any],
    attributes: dict[str, Any],
    enrichment: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """What `{{...}}` can reference. `enrichment` = {connectorKey: {field: value}}."""
    return {
        "case": {
            "case_number": case_number,
            "channel": channel,
            "language": language,
            "category": category or {},
            "customer": customer,
            "attributes": attributes,
        },
        "enrichment": enrichment,
    }
