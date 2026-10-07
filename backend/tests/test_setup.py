"""The setup checklist (by where the business sells) and the integrations overview."""

from typing import Any

from fastapi.testclient import TestClient

from app.ai.reading import PATTERN_PRESETS, find_candidates


def setup(client: TestClient, tenant_id: str, **profile: Any) -> dict[str, Any]:
    response = client.put(f"/tenants/{tenant_id}/setup", json=profile)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def steps(info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in info["steps"]}


def cards(client: TestClient, tenant_id: str) -> dict[str, dict[str, Any]]:
    body = client.get(f"/tenants/{tenant_id}/integrations").json()
    return {c["key"]: c for c in body["cards"]}


def link_inbox(client: TestClient, tenant_id: str) -> None:
    response = client.post(
        f"/tenants/{tenant_id}/mailboxes",
        json={
            "name": "Seller inbox",
            "address": "seller@harbor.example.com",
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "username": "seller@harbor.example.com",
            "password": "app-password",
        },
    )
    assert response.status_code == 201, response.text


def test_new_business_has_no_profile(client: TestClient, tenant_id: str) -> None:
    info = client.get(f"/tenants/{tenant_id}/setup").json()
    assert info["profile"] == {"sells_on": [], "marketplaces": [], "completed": False}
    assert "SHOP.COM" in info["marketplaces"]
    assert [s["key"] for s in info["steps"]] == ["inbox", "reading", "rules"]


def test_marketplace_seller_works_by_email(client: TestClient, tenant_id: str) -> None:
    info = setup(client, tenant_id, marketplaces=["SHOP.COM", " SHOP.COM "])
    assert info["profile"]["sells_on"] == ["marketplace"]  # implied by the marketplace list
    assert info["profile"]["marketplaces"] == ["SHOP.COM"]
    assert info["applied"] == ["Reading order numbers out of customers' emails is now on."]
    s = steps(info)
    assert list(s) == ["inbox", "reading", "rules"]  # no Shopify, no Stripe
    assert "SHOP.COM seller account" in s["inbox"]["detail"]
    assert "issue those refunds in your seller dashboard" in s["rules"]["detail"]
    assert s["reading"]["done"] and not s["inbox"]["done"]

    reading = client.get(f"/tenants/{tenant_id}/reading").json()["settings"]
    assert reading["enabled"] and reading["fields"][0]["key"] == "orderNumber"

    c = cards(client, tenant_id)
    assert c["marketplaces"]["recommended"] and c["marketplaces"]["status"] == "not_connected"
    assert not c["shopify"]["recommended"]
    link_inbox(client, tenant_id)
    assert steps(client.get(f"/tenants/{tenant_id}/setup").json())["inbox"]["done"]
    assert cards(client, tenant_id)["marketplaces"]["status"] == "connected"


def test_defaults_never_overwrite_existing_settings(client: TestClient, tenant_id: str) -> None:
    client.put(f"/tenants/{tenant_id}/reading", json={"enabled": False, "fields": []})
    client.put(
        f"/tenants/{tenant_id}/reading",
        json={
            "enabled": False,
            "fields": [
                {
                    "key": "sku",
                    "label": "SKU",
                    "description": "the product code",
                    "pattern": "X\\d+",
                }
            ],
        },
    )
    info = setup(client, tenant_id, sells_on=["own_site"])
    assert info["applied"] == []
    assert (
        client.get(f"/tenants/{tenant_id}/reading").json()["settings"]["fields"][0]["key"] == "sku"
    )
    assert {"payouts_stripe", "connectors"} <= set(steps(info))
    assert steps(info)["connectors"]["optional"]


def test_shopify_seller_gets_shopify_steps(client: TestClient, tenant_id: str) -> None:
    info = setup(client, tenant_id, sells_on=["shopify", "marketplace"], marketplaces=["Etsy"])
    s = steps(info)
    assert list(s)[:2] == ["shopify", "inbox"] and "payouts_shopify" in s
    assert "Shopify store's customer email" in s["inbox"]["detail"]
    assert "Etsy seller account" in s["inbox"]["detail"]
    assert not s["shopify"]["done"]
    c = cards(client, tenant_id)
    assert c["shopify"]["recommended"] and c["shopify"]["status"] == "not_connected"
    assert c["woocommerce"]["status"] == "coming_soon"
    assert c["webform"]["status"] == "connected"
    assert {card["group"] for card in c.values()} == {"store", "messages", "payments", "systems"}


def test_profile_validation(client: TestClient, tenant_id: str) -> None:
    response = client.put(f"/tenants/{tenant_id}/setup", json={"sells_on": ["mars"]})
    assert response.status_code == 422
    assert client.get("/tenants/00000000-0000-0000-0000-000000000000/setup").status_code == 404


def test_order_number_preset_finds_all_common_formats() -> None:
    text = "My order #1006 (also NW-10211 and SHOP.COM order 104821377) is late."
    found = find_candidates(PATTERN_PRESETS["order"][0], text)
    assert {c.value for c in found} == {"#1006", "NW-10211", "104821377"}
