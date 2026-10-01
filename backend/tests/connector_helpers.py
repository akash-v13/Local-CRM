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


API_KEY_CREDENTIAL: dict[str, Any] = {
    "name": "Shop API key",
    "kind": "api_key",
    "config": {"header_name": "X-Api-Key"},
    "secrets": {"key": "super-secret-key"},
}


def create_credential(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    body = {**API_KEY_CREDENTIAL, **overrides}
    response = client.post(f"/tenants/{tenant_id}/credentials", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def shop_api_key_credential_id(client: TestClient, tenant_id: str) -> str:
    """The shop's API-key credential, created on first use."""
    existing = client.get(f"/tenants/{tenant_id}/credentials").json()
    for credential in existing:
        if credential["name"] == API_KEY_CREDENTIAL["name"]:
            return str(credential["id"])
    return str(create_credential(client, tenant_id)["id"])


def create_connector(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    """The shop connector (with the shop's API key unless `credential_id` is overridden)."""
    body = {**SHOP_CONNECTOR, **overrides}
    if "credential_id" not in body:
        body["credential_id"] = shop_api_key_credential_id(client, tenant_id)
    response = client.post(f"/tenants/{tenant_id}/connectors", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created
