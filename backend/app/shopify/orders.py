"""A Shopify order -> the flat fields saved on a case as enrichment.shopify.<field>.

Pure functions (no HTTP, no database), so they're easy to test. Routing and
compensation rules, AI templates and connectors use these field names, e.g.
`enrichment.shopify.daysLate greater than 3`.
"""

import re
from datetime import datetime
from typing import Any

from app.domain.routing import to_number

# key -> label (shown in the condition builder and on the case)
SHOPIFY_FIELDS: dict[str, str] = {
    "orderNumber": "Order number",
    "orderDate": "Order date",
    "orderTotal": "Order total",
    "currency": "Currency",
    "financialStatus": "Payment status",
    "fulfillmentStatus": "Fulfilment status",
    "deliveryStatus": "Delivery status",
    "carrier": "Carrier",
    "trackingNumber": "Tracking number",
    "trackingUrl": "Tracking link",
    "estimatedDelivery": "Estimated delivery",
    "deliveredAt": "Delivered",
    "daysLate": "Days late",
    "refundedTotal": "Already refunded",
    "cancelled": "Cancelled",
    "tags": "Order tags",
    "customerOrders": "Customer's orders",
    "customerSpent": "Customer's total spend",
    "matchedBy": "Found by",
    "orderId": "Shopify order id",
    "customerId": "Shopify customer id",
}

_SAFE = re.compile(r"[^A-Za-z0-9#\-_./]")


def order_search(order_number: str) -> str | None:
    """The orders(query:) filter for an order number: "1001" -> name:"#1001"."""
    value = _SAFE.sub("", str(order_number).strip())
    if not value or value == "#":
        return None
    if value.isdigit():
        value = "#" + value
    return f'name:"{value}"'


def email_search(email: str) -> str:
    return 'email:"' + email.replace('"', "").replace("\\", "").strip() + '"'


def same_order_name(name: str, wanted: str) -> bool:
    """Shopify search is fuzzy-ish: make sure "#1001" doesn't match "#10012"."""

    def norm(v: str) -> str:
        return v.strip().lstrip("#").upper()

    return norm(name) == norm(wanted)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _money(value: Any) -> float | None:
    return to_number(((value or {}).get("shopMoney") or {}).get("amount"))


def order_fields(order: dict[str, Any], *, now: datetime, matched_by: str) -> dict[str, Any]:
    """The case fields for an order. `now` (UTC) is used for orders not delivered yet."""
    fulfillments = order.get("fulfillments") or []
    # The latest shipment tells the story (split shipments: the last one to arrive).
    latest: dict[str, Any] = max(fulfillments, key=lambda f: f.get("createdAt") or "", default={})
    tracking = (latest.get("trackingInfo") or [{}])[0] if latest else {}
    estimated = _date(latest.get("estimatedDeliveryAt"))
    delivered = _date(latest.get("deliveredAt"))
    days_late: int | None = None
    if estimated is not None:
        late_by = (delivered or now) - estimated
        days_late = max(0, late_by.days)
    customer = order.get("customer") or {}
    created = _date(order.get("createdAt"))
    fields: dict[str, Any] = {
        "orderNumber": order.get("name"),
        "orderDate": created.date().isoformat() if created else None,
        "orderTotal": _money(order.get("totalPriceSet")),
        "currency": order.get("currencyCode"),
        "financialStatus": order.get("displayFinancialStatus"),
        "fulfillmentStatus": order.get("displayFulfillmentStatus"),
        "deliveryStatus": latest.get("displayStatus"),
        "carrier": tracking.get("company"),
        "trackingNumber": tracking.get("number"),
        "trackingUrl": tracking.get("url"),
        "estimatedDelivery": estimated.date().isoformat() if estimated else None,
        "deliveredAt": delivered.date().isoformat() if delivered else None,
        "daysLate": days_late,
        "refundedTotal": _money(order.get("totalRefundedSet")),
        "cancelled": bool(order.get("cancelledAt")),
        "tags": ", ".join(order.get("tags") or []) or None,
        "customerOrders": to_number(customer.get("numberOfOrders")),
        "customerSpent": to_number((customer.get("amountSpent") or {}).get("amount")),
        "matchedBy": matched_by,
        "orderId": order.get("id"),
        "customerId": customer.get("id"),
    }
    return {k: v for k, v in fields.items() if v is not None}
