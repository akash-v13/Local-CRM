"""A fake "shop + shipping" API for demos, run as the `mocks` service in docker-compose.

    uv run uvicorn mocks.shop:app --port 8100

Endpoints (all JSON):

  POST /oauth/token            OAuth 2.0 client credentials.
                               client_id=demo-client, client_secret=demo-secret
                               → {"access_token": "...", "expires_in": 300}
  GET  /orders/{orderNumber}   Needs "Authorization: Bearer <token>" from /oauth/token.
  GET  /shipments/{tracking}   Needs "X-Api-Key: demo-key".
  GET  /loyalty/{email}        Needs "Authorization: Bearer demo-loyalty-token".
  /stripe/v1/…                 A tiny fake Stripe (key sk_test_mock): payments for every
                               order (pi_mock_<order>), customers, refunds, balance credits,
                               coupons and promotion codes, with idempotency replay.
  GET  /health

Order data is made up but deterministic: the same order number always gives
the same answer. Special order numbers for testing failures:
  ...404...   → 404 Not Found
  ...500...   → 500 Server Error
  ...SLOW...  → waits 8 seconds (try a 5s connector timeout)

Inside docker-compose, connectors reach it at http://mocks:8100.
"""

import hashlib
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import FastAPI, Form, Header, HTTPException, Request

app = FastAPI(title="Mock shop & shipping API")

CLIENT_ID, CLIENT_SECRET = "demo-client", "demo-secret"
API_KEY = "demo-key"
LOYALTY_TOKEN = "demo-loyalty-token"
TOKEN_LIFETIME_SECONDS = 300
_tokens: dict[str, float] = {}  # token → expiry (unix time)

CARRIERS = ["FastShip", "ParcelGo", "SwiftPost"]
FAULTS = [
    ("carrier", "Carrier capacity"),
    ("weather", "Severe weather"),
    ("merchant", "Packed late"),
]


def _number(seed: str, low: int, high: int) -> int:
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return low + digest % (high - low + 1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/oauth/token")
def token(
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
) -> dict[str, Any]:
    if grant_type != "client_credentials":
        raise HTTPException(400, detail="unsupported_grant_type")
    if (client_id, client_secret) != (CLIENT_ID, CLIENT_SECRET):
        raise HTTPException(401, detail="invalid_client")
    value = secrets.token_urlsafe(24)
    _tokens[value] = time.time() + TOKEN_LIFETIME_SECONDS
    return {"access_token": value, "token_type": "bearer", "expires_in": TOKEN_LIFETIME_SECONDS}


def _require_token(authorization: str | None) -> None:
    value = (authorization or "").removeprefix("Bearer ").strip()
    if _tokens.get(value, 0) < time.time():
        raise HTTPException(401, detail="invalid_or_expired_token")


@app.get("/orders/{order_number}")
def order(
    order_number: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _require_token(authorization)
    if "404" in order_number:
        raise HTTPException(404, detail="order not found")
    if "500" in order_number:
        raise HTTPException(500, detail="internal error")
    if "SLOW" in order_number.upper():
        time.sleep(8)

    promised = date(2026, 9, 1) + timedelta(days=_number(order_number + "p", 0, 25))
    days_late = _number(order_number + "late", 0, 9)
    delivered = datetime.combine(promised + timedelta(days=days_late), datetime.min.time(), UTC)
    carrier = CARRIERS[_number(order_number + "c", 0, len(CARRIERS) - 1)]
    return {
        "orderNumber": order_number,
        "status": "delivered",
        "total": {"amount": _number(order_number + "t", 1500, 95000) / 100, "currency": "USD"},
        "promisedDeliveryDate": promised.isoformat(),
        "deliveredAt": delivered.isoformat(),
        "daysLate": days_late,
        "carrier": carrier,
        "trackingNumber": f"TRK{_number(order_number + 'k', 100000, 999999)}",
        "paymentIntentId": f"pi_mock_{order_number.replace('-', '_')}",
        "items": [
            {"sku": f"SKU-{_number(order_number + str(i), 100, 999)}", "quantity": 1}
            for i in range(_number(order_number + "n", 1, 3))
        ],
    }


@app.get("/shipments/{tracking_number}")
def shipment(
    tracking_number: str, x_api_key: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    if x_api_key != API_KEY:
        raise HTTPException(401, detail="invalid api key")
    fault, reason = FAULTS[_number(tracking_number, 0, len(FAULTS) - 1)]
    return {
        "trackingNumber": tracking_number,
        "fault": fault,
        "delayReason": reason,
        "events": [
            {"at": "2026-09-02T08:00:00Z", "status": "picked_up"},
            {"at": "2026-09-05T17:30:00Z", "status": "delayed", "note": reason},
            {"at": "2026-09-09T11:15:00Z", "status": "delivered"},
        ],
    }


@app.get("/loyalty/{email}")
def loyalty(email: str, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """Loyalty program membership for a customer email (made up, deterministic)."""
    if authorization != f"Bearer {LOYALTY_TOKEN}":
        raise HTTPException(401, detail="invalid token")
    return {
        "email": email,
        "memberSince": f"20{_number(email + 'y', 18, 25)}-0{_number(email + 'm', 1, 9)}-01",
        "points": _number(email + "p", 0, 12000),
        "ordersLast12Months": _number(email + "o", 1, 24),
        "compensationClaimsLast12Months": _number(email + "c", 0, 3),
    }


# ----- fake Stripe ------------------------------------------------------------------------
# Enough of api.stripe.com for the payout demo. Every order has a USD PaymentIntent
# (pi_mock_<order>, metadata.order_id=<order>); every email has a customer. State is
# in memory and resets when the service restarts.

STRIPE_KEY = "sk_test_mock"
_stripe: dict[str, Any] = {"refunds": [], "balance": [], "coupons": [], "promos": [], "replay": {}}


def _stripe_auth(authorization: str | None) -> None:
    if authorization != f"Bearer {STRIPE_KEY}":
        raise HTTPException(401, detail={"error": {"message": "Invalid API Key provided"}})


def _intent(intent_id: str) -> dict[str, Any]:
    order = intent_id.removeprefix("pi_mock_").replace("_", "-")
    total = _number(order + "t", 1500, 95000)
    return {
        "id": intent_id,
        "object": "payment_intent",
        "amount": total,
        "amount_received": total,
        "currency": "usd",
        "metadata": {"order_id": order},
        "livemode": False,
    }


def _metadata(form: dict[str, str]) -> dict[str, str]:
    return {k[9:-1]: v for k, v in form.items() if k.startswith("metadata[")}


@app.get("/stripe/v1/balance")
def stripe_balance(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    _stripe_auth(authorization)
    return {
        "object": "balance",
        "livemode": False,
        "available": [{"amount": 500000, "currency": "usd"}],
    }


@app.get("/stripe/v1/payment_intents/search")
def stripe_search(
    query: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _stripe_auth(authorization)
    order = query.split(":'", 1)[1].rstrip("'") if ":'" in query else ""
    found = [] if not order or "404" in order else [_intent("pi_mock_" + order.replace("-", "_"))]
    return {"object": "search_result", "data": found}


@app.get("/stripe/v1/payment_intents/{intent_id}")
def stripe_intent(
    intent_id: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _stripe_auth(authorization)
    return _intent(intent_id)


@app.get("/stripe/v1/customers")
def stripe_customers(
    email: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _stripe_auth(authorization)
    return {
        "object": "list",
        "data": [{"id": f"cus_mock_{_number(email, 10000, 99999)}", "email": email}],
    }


@app.get("/stripe/v1/refunds")
def stripe_list_refunds(
    payment_intent: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _stripe_auth(authorization)
    return {
        "object": "list",
        "data": [r for r in _stripe["refunds"] if r["payment_intent"] == payment_intent],
    }


@app.get("/stripe/v1/promotion_codes")
def stripe_list_promos(
    code: str, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    _stripe_auth(authorization)
    return {"object": "list", "data": [p for p in _stripe["promos"] if p["code"] == code]}


@app.post("/stripe/v1/{path:path}")
async def stripe_post(
    path: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    _stripe_auth(authorization)
    form = {k: str(v) for k, v in (await request.form()).items()}
    if idempotency_key and idempotency_key in _stripe["replay"]:
        original, replayed = _stripe["replay"][idempotency_key]
        if original != form:
            raise HTTPException(
                400,
                detail={
                    "error": {
                        "type": "idempotency_error",
                        "message": "Idempotency key reused with different parameters.",
                    }
                },
            )
        return replayed
    meta = _metadata(form)
    result: dict[str, Any]
    if path == "refunds":
        intent = _intent(form["payment_intent"])
        if "404" in intent["metadata"]["order_id"]:
            raise HTTPException(400, detail={"error": {"message": "No such payment_intent"}})
        result = {
            "id": f"re_mock_{len(_stripe['refunds']) + 1}",
            "object": "refund",
            "amount": int(form["amount"]),
            "currency": "usd",
            "status": "succeeded",
            "payment_intent": form["payment_intent"],
            "metadata": meta,
        }
        _stripe["refunds"].append(result)
    elif path.startswith("customers/") and path.endswith("/balance_transactions"):
        result = {
            "id": f"cbtxn_mock_{len(_stripe['balance']) + 1}",
            "object": "customer_balance_transaction",
            "amount": int(form["amount"]),
            "currency": form["currency"],
            "ending_balance": int(form["amount"]),
            "metadata": meta,
        }
        _stripe["balance"].append(result)
    elif path == "coupons":
        result = {
            "id": f"co_mock_{len(_stripe['coupons']) + 1}",
            "object": "coupon",
            "amount_off": int(form["amount_off"]),
            "currency": form["currency"],
            "metadata": meta,
        }
        _stripe["coupons"].append(result)
    elif path == "promotion_codes":
        result = {
            "id": f"promo_mock_{len(_stripe['promos']) + 1}",
            "object": "promotion_code",
            "code": form["code"],
            "customer": form.get("customer"),
            "promotion": {"type": "coupon", "coupon": form["promotion[coupon]"]},
            "metadata": meta,
        }
        _stripe["promos"].append(result)
    else:
        raise HTTPException(404, detail={"error": {"message": "Unrecognized request URL"}})
    if idempotency_key:
        _stripe["replay"][idempotency_key] = (form, result)
    return result
