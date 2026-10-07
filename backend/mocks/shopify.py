"""A tiny fake Shopify Admin API for demos (mounted by mocks/shop.py under /shopify).

Just enough for Local CRM's order lookup and payouts, for any store name:

  POST /shopify/<shop>/admin/oauth/access_token        client credentials grant
       client_id=demo-shopify-client, client_secret=demo-shopify-secret → 24-hour token
  POST /shopify/<shop>/admin/api/<version>/graphql.json  X-Shopify-Access-Token: <token>
       operations (by operationName): LcrmShop, LcrmOrders, LcrmOrderPayments,
       LcrmRefund (honours the idempotency key), LcrmStoreCredit, LcrmDiscount,
       LcrmDiscountByCode
  POST /shopify/<shop>/_demo/customers                  {"<order number>": "<email>"}
       (demo only) who placed which order, so "order email matches" works. The demo
       store's orders (DEMO_OWNERS) are known from the start.

Orders use the same made-up numbers as GET /orders/{n} (total, promised date, days
late, carrier). Order numbers containing 404 don't exist. Nothing is real: state lives
in memory and resets when the service restarts.
"""

import hashlib
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Form, Header, HTTPException, Request

router = APIRouter(prefix="/shopify/{shop}")

CLIENT_ID, CLIENT_SECRET = "demo-shopify-client", "demo-shopify-secret"
TOKEN_SECONDS = 86_399
CARRIERS = ["FastShip", "ParcelGo", "SwiftPost"]

# Who placed the demo store's orders (scripts/seed_demo.py), so they survive a restart.
DEMO_OWNERS = {
    "#1006": "priya.raman@example.com",
    "#1020": "marco.rossi@example.com",
    "#1023": "jin.park@example.com",
    "#1013": "owen.hart@example.com",
}

_tokens: dict[str, float] = {}
_state: dict[str, Any] = {
    "owners": dict(DEMO_OWNERS),  # order number -> customer email
    "orders": {},  # gid -> order number
    "refunds": {},  # order number -> [refund]
    "idempotency": {},  # key -> (input, result)
    "credit": {},  # customer gid -> balance
    "codes": {},  # code -> discount node
}


def _number(seed: str, low: int, high: int) -> int:
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return low + digest % (high - low + 1)


def _money(amount: float) -> dict[str, Any]:
    value = {"amount": f"{amount:.2f}", "currencyCode": "USD"}
    return {"shopMoney": value, "presentmentMoney": value}


def _gid(kind: str, seed: str) -> str:
    return f"gid://shopify/{kind}/{_number(seed, 10**9, 10**10)}"


def _customer_gid(email: str) -> str:
    return f"gid://shopify/Customer/{_number(email.lower(), 10**9, 10**10)}"


def _order(name: str) -> dict[str, Any]:
    promised = date(2026, 9, 1) + timedelta(days=_number(name + "p", 0, 25))
    days_late = _number(name + "late", 0, 9)
    estimated = datetime.combine(promised, datetime.min.time(), UTC)
    delivered = estimated + timedelta(days=days_late)
    total = _number(name + "t", 1500, 95000) / 100
    refunded = sum(float(r["amount"]) for r in _state["refunds"].get(name, []))
    gid = f"gid://shopify/Order/{_number(name, 10**9, 10**10)}"
    _state["orders"][gid] = name
    email = _state["owners"].get(name, f"{name.lower()}@customers.example.com")
    tracking = f"TRK{_number(name + 'k', 100000, 999999)}"
    return {
        "id": gid,
        "name": name,
        "createdAt": (estimated - timedelta(days=6)).isoformat(),
        "cancelledAt": None,
        "displayFinancialStatus": "PARTIALLY_REFUNDED" if refunded else "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "currencyCode": "USD",
        "presentmentCurrencyCode": "USD",
        "totalPriceSet": _money(total),
        "totalRefundedSet": _money(refunded),
        "tags": [],
        "customer": {
            "id": _customer_gid(email),
            "numberOfOrders": str(_number(email, 1, 9)),
            "amountSpent": {
                "amount": f"{_number(email + 's', 50, 900):.2f}",
                "currencyCode": "USD",
            },
            "defaultEmailAddress": {"emailAddress": email},
        },
        "fulfillments": [
            {
                "createdAt": (estimated - timedelta(days=4)).isoformat(),
                "displayStatus": "DELIVERED",
                "estimatedDeliveryAt": estimated.isoformat(),
                "inTransitAt": (estimated - timedelta(days=3)).isoformat(),
                "deliveredAt": delivered.isoformat(),
                "trackingInfo": [
                    {
                        "number": tracking,
                        "company": CARRIERS[_number(name + "c", 0, len(CARRIERS) - 1)],
                        "url": f"https://tracking.example.com/{tracking}",
                    }
                ],
            }
        ],
        "_total": total,
        "_refunded": refunded,
    }


def _public(order: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in order.items() if not k.startswith("_")}


def _search(query: str) -> list[dict[str, Any]]:
    field, _, value = query.partition(":")
    value = value.strip().strip('"')
    if field == "name":
        return [] if not value.lstrip("#") or "404" in value else [_order(value)]
    if field == "email":
        names = [n for n, e in _state["owners"].items() if e == value.lower()]
        return [_order(n) for n in sorted(names, reverse=True)[:1]]
    return []


@router.post("/admin/oauth/access_token")
def access_token(
    shop: str,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
) -> dict[str, Any]:
    if grant_type != "client_credentials" or (client_id, client_secret) != (
        CLIENT_ID,
        CLIENT_SECRET,
    ):
        raise HTTPException(400, detail={"error": "invalid_client"})
    value = "shpat_mock_" + secrets.token_hex(12)
    _tokens[value] = time.time() + TOKEN_SECONDS
    return {"access_token": value, "scope": "read_orders,write_orders", "expires_in": TOKEN_SECONDS}


@router.post("/_demo/customers")
async def demo_customers(shop: str, request: Request) -> dict[str, int]:
    owners: dict[str, str] = await request.json()
    _state["owners"].update({k: v.lower() for k, v in owners.items()})
    return {"orders": len(_state["owners"])}


def _errors(code: str, message: str) -> dict[str, Any]:
    return {"errors": [{"message": message, "extensions": {"code": code}}]}


@router.post("/admin/api/{version}/graphql.json")
async def graphql(
    shop: str,
    version: str,
    request: Request,
    x_shopify_access_token: Annotated[str | None, Header()] = None,
) -> Any:
    if _tokens.get(x_shopify_access_token or "", 0) < time.time():
        raise HTTPException(401, detail={"errors": "[API] Invalid API key or access token"})
    body = await request.json()
    op, v = body.get("operationName"), body.get("variables") or {}
    if op == "LcrmShop":
        return {
            "data": {
                "shop": {"name": "Harbor Goods", "currencyCode": "USD", "myshopifyDomain": shop}
            }
        }
    if op == "LcrmOrders":
        found = _search(v.get("query", ""))[: v.get("first", 5)]
        return {"data": {"orders": {"nodes": [_public(o) for o in found]}}}
    if op == "LcrmOrderPayments":
        name = _state["orders"].get(v.get("id"))
        if name is None:
            return {"data": {"order": None}}
        order = _order(name)
        return {
            "data": {
                "order": {
                    "id": order["id"],
                    "name": name,
                    "presentmentCurrencyCode": "USD",
                    "transactions": [
                        {
                            "id": _gid("OrderTransaction", name + "tx"),
                            "kind": "SALE",
                            "status": "SUCCESS",
                            "gateway": "shopify_payments",
                            "amountSet": _money(order["_total"]),
                        }
                    ],
                    "refunds": [
                        {
                            "id": r["id"],
                            "note": r["note"],
                            "totalRefundedSet": _money(float(r["amount"])),
                        }
                        for r in _state["refunds"].get(name, [])
                    ],
                }
            }
        }
    if op == "LcrmRefund":
        key = v.get("key")
        if not key:
            return _errors("BAD_REQUEST", "The @idempotent directive is required for refundCreate.")
        if key in _state["idempotency"]:
            original, result = _state["idempotency"][key]
            if original != v["input"]:
                return _errors("IDEMPOTENCY_KEY_PARAMETER_MISMATCH", "Idempotency key reused.")
            return result
        name = _state["orders"].get(v["input"]["orderId"])
        txn = (v["input"].get("transactions") or [{}])[0]
        amount = float(txn.get("amount", 0))
        if name is None:
            payload: dict[str, Any] = {
                "refund": None,
                "userErrors": [{"field": ["orderId"], "message": "Order does not exist"}],
            }
        elif amount > _order(name)["_total"] - _order(name)["_refunded"] + 0.001:
            payload = {
                "refund": None,
                "userErrors": [
                    {
                        "field": ["transactions"],
                        "message": "Refund amount exceeds the refundable amount",
                    }
                ],
            }
        else:
            refund = {
                "id": _gid("Refund", key),
                "note": v["input"].get("note"),
                "amount": f"{amount:.2f}",
            }
            _state["refunds"].setdefault(name, []).append(refund)
            payload = {
                "refund": {
                    "id": refund["id"],
                    "note": refund["note"],
                    "totalRefundedSet": _money(amount),
                },
                "userErrors": [],
            }
        result = {"data": {"refundCreate": payload}}
        _state["idempotency"][key] = (v["input"], result)
        return result
    if op == "LcrmStoreCredit":
        customer = v["id"]
        amount = float(v["creditInput"]["creditAmount"]["amount"])
        _state["credit"][customer] = _state["credit"].get(customer, 0.0) + amount
        account = f"gid://shopify/StoreCreditAccount/{_number(customer, 10**8, 10**9)}"
        return {
            "data": {
                "storeCreditAccountCredit": {
                    "storeCreditAccountTransaction": {
                        "amount": {"amount": f"{amount:.2f}", "currencyCode": "USD"},
                        "account": {
                            "id": account,
                            "balance": {
                                "amount": f"{_state['credit'][customer]:.2f}",
                                "currencyCode": "USD",
                            },
                        },
                    },
                    "userErrors": [],
                }
            }
        }
    if op == "LcrmDiscount":
        discount = v["discount"]
        code = discount["code"]
        if code in _state["codes"]:
            return {
                "data": {
                    "discountCodeBasicCreate": {
                        "codeDiscountNode": None,
                        "userErrors": [
                            {
                                "field": ["basicCodeDiscount", "code"],
                                "code": "TAKEN",
                                "message": "Code must be unique. Please try a different code.",
                            }
                        ],
                    }
                }
            }
        node = {
            "id": f"gid://shopify/DiscountCodeNode/{_number(code, 10**9, 10**10)}",
            "codeDiscount": {"title": discount["title"]},
        }
        _state["codes"][code] = node
        return {
            "data": {
                "discountCodeBasicCreate": {
                    "codeDiscountNode": {"id": node["id"]},
                    "userErrors": [],
                }
            }
        }
    if op == "LcrmDiscountByCode":
        return {"data": {"codeDiscountNodeByCode": _state["codes"].get(v.get("code"))}}
    return _errors("BAD_REQUEST", f"The mock doesn't know {op}.")
