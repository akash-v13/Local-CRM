"""Reading values out of JSON with simple dotted paths.

    extract({"order": {"items": [{"sku": "A1"}]}}, "order.items.0.sku")  ->  (True, "A1")

A path segment is a dict key, or a list index when the current value is a list.
Used for connector field mappings and for `{{placeholders}}`.
"""

from typing import Any


def extract(data: Any, path: str) -> tuple[bool, Any]:
    """Return (found, value). `found` is False if any segment is missing."""
    current = data
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            return False, None
    return True, current
