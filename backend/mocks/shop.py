"""A fake "shop + shipping" API for demos, run as the `mocks` service in docker-compose.

    uv run uvicorn mocks.shop:app --port 8100

Endpoints (all JSON):

  POST /oauth/token            OAuth 2.0 client credentials.
                               client_id=demo-client, client_secret=demo-secret
                               → {"access_token": "...", "expires_in": 300}
  GET  /orders/{orderNumber}   Needs "Authorization: Bearer <token>" from /oauth/token.
  GET  /shipments/{tracking}   Needs "X-Api-Key: demo-key".
  GET  /loyalty/{email}        Needs "Authorization: Bearer demo-loyalty-token".
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

from fastapi import FastAPI, Form, Header, HTTPException

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
