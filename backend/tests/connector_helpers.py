"""Shared helpers for connector and enrichment tests."""

from typing import Any

import httpx
from fastapi.testclient import TestClient

SHOP_ORDER = {
    "orderNumber": "ORD-55012",
    "total": {"amount": 742.5, "currency": "USD"},
    "carrier": "FastShip",
    "trackingNumber": "TRK123",
    "daysLate": 6,
    "items": [{"sku": "A1"}],
}

SHOP_CONNECTOR: dict[str, Any] = {
    "key": "shop",
    "name": "Shop orders",
    "url_template": "https://shop.example.com/orders/{{case.attributes.orderNumber}}",
    "auth_type": "api_key",
    "auth_header_name": "X-Api-Key",
    "secret": "super-secret-key",
    "max_retries": 0,
    "field_mappings": [
        {"path": "total.amount", "target": "orderTotal", "label": "Order total"},
        {"path": "carrier", "target": "carrier"},
        {"path": "trackingNumber", "target": "trackingNumber"},
        {"path": "daysLate", "target": "daysLate"},
    ],
}


def shop_api(request: httpx.Request) -> httpx.Response:
    """A fake shop: answers /orders/<number> when the API key is right."""
    if request.headers.get("X-Api-Key") != "super-secret-key":
        return httpx.Response(401, json={"error": "bad key"})
    if request.url.path == "/orders/ORD-55012":
        return httpx.Response(200, json=SHOP_ORDER)
    if request.url.path.startswith("/shipments/"):
        return httpx.Response(200, json={"fault": "carrier", "tracking": request.url.path[11:]})
    return httpx.Response(404, json={"error": "not found"})


def create_connector(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/connectors", json={**SHOP_CONNECTOR, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
