"""Issuing compensation through the business's own Stripe account.

Verified against docs.stripe.com (October 2026):

- Refund:        POST /v1/refunds  payment_intent=pi_…  amount=<minor units>
                 reason=requested_by_customer
- Store credit:  POST /v1/customers/{id}/balance_transactions  amount=-<minor units>  currency=usd
                 (a negative amount is a credit, applied to the customer's next invoices)
- Voucher:       POST /v1/coupons  amount_off=<minor units> currency duration=once max_redemptions=1
                 POST /v1/promotion_codes  promotion[type]=coupon promotion[coupon]=<id>  code=…
                 customer=cus_… max_redemptions=1 expires_at=<unix>
- Lookups:       GET /v1/payment_intents/search?query=metadata['order_id']:'NW-10211'
                 GET /v1/customers?email=…
- Key check:     GET /v1/balance

Every POST carries an `Idempotency-Key`: Stripe replays the first result for the same
key (for at least 24 hours), so a retry after a network error can't refund twice.
Stripe also replays *errors*, including 500s, and after a 500 the operation may or may
not have happened. So after a 5xx the caller first looks for its own object (every
object we create carries `metadata[payout_id]`) and only then retries with a new key.
Requests are form-encoded; amounts are integers in the currency's smallest unit.
Stripe never sends money to arbitrary people: "Payouts" in Stripe are the business
withdrawing to its own bank, so cash to customers needs a different provider.
"""

from dataclasses import dataclass
from typing import Any

import httpx

STRIPE_API = "https://api.stripe.com"

# Currencies Stripe charges in whole units (no cents); docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv",
    "xaf", "xof", "xpf",
}  # fmt: skip


def to_minor(amount: float, currency: str) -> int:
    """19.99 USD -> 1999; 1500 JPY -> 1500."""
    return int(round(amount if currency.lower() in ZERO_DECIMAL else amount * 100))


def from_minor(amount: int, currency: str) -> float:
    return float(amount) if currency.lower() in ZERO_DECIMAL else amount / 100


class StripeError(Exception):
    """A Stripe request failed. `retryable` = worth trying again (network, 429, 5xx)."""

    def __init__(
        self, message: str, *, retryable: bool, code: str | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code
        self.status = status  # None = no response (network error)

    @property
    def outcome_unknown(self) -> bool:
        """A 5xx: Stripe may have done it, and replays the 500 for the same key."""
        return self.status is not None and self.status >= 500


@dataclass(frozen=True)
class StripeAccount:
    mode: str  # "test" or "live"
    currencies: list[str]


class StripeClient:
    def __init__(self, http: httpx.Client, secret_key: str, base_url: str = STRIPE_API) -> None:
        self.http = http
        self.key = secret_key
        self.base = base_url.rstrip("/")

    @property
    def mode(self) -> str:
        return "live" if self.key.startswith(("sk_live", "rk_live")) else "test"

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:255]
        try:
            response = self.http.request(
                method, self.base + path, data=data, params=params, headers=headers, timeout=30
            )
        except httpx.HTTPError as exc:
            raise StripeError(
                f"Couldn't reach Stripe ({type(exc).__name__}).", retryable=True
            ) from exc
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if response.status_code < 400:
            return body
        error = body.get("error") or {}
        message = error.get("message") or f"HTTP {response.status_code}"
        if response.status_code == 401:
            raise StripeError(
                "Stripe rejected the API key. Check the Stripe credential.", retryable=False
            )
        retryable = response.status_code == 429 or response.status_code >= 500
        raise StripeError(
            f"Stripe: {message}",
            retryable=retryable,
            code=error.get("code"),
            status=response.status_code,
        )

    # ----- checks and lookups ---------------------------------------------------------------

    def account(self) -> StripeAccount:
        balance = self._request("GET", "/v1/balance")
        currencies = sorted(
            {b.get("currency", "") for b in balance.get("available", []) if b.get("currency")}
        )
        return StripeAccount(
            mode="live" if balance.get("livemode") else "test", currencies=currencies
        )

    def find_payment_by_metadata(self, key: str, value: str) -> str | None:
        """The most recent PaymentIntent whose metadata[key] == value."""
        safe = value.replace("\\", "\\\\").replace("'", "\\'")
        result = self._request(
            "GET",
            "/v1/payment_intents/search",
            params={"query": f"metadata['{key}']:'{safe}'", "limit": 1},
        )
        data = result.get("data") or []
        return str(data[0]["id"]) if data else None

    def payment_intent(self, payment_intent: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/payment_intents/{payment_intent}")

    def find_customer(self, email: str) -> str | None:
        result = self._request("GET", "/v1/customers", params={"email": email, "limit": 1})
        data = result.get("data") or []
        return str(data[0]["id"]) if data else None

    # ----- finding what an earlier attempt created (after a 5xx) -------------------------

    def find_refund(self, payment_intent: str, payout_id: str) -> dict[str, Any] | None:
        result = self._request(
            "GET", "/v1/refunds", params={"payment_intent": payment_intent, "limit": 100}
        )
        return next(
            (
                r
                for r in result.get("data", [])
                if r.get("metadata", {}).get("payout_id") == payout_id
            ),
            None,
        )

    def find_credit(self, customer: str, payout_id: str) -> dict[str, Any] | None:
        result = self._request(
            "GET", f"/v1/customers/{customer}/balance_transactions", params={"limit": 100}
        )
        return next(
            (
                t
                for t in result.get("data", [])
                if t.get("metadata", {}).get("payout_id") == payout_id
            ),
            None,
        )

    def find_promotion_code(self, code: str) -> dict[str, Any] | None:
        result = self._request("GET", "/v1/promotion_codes", params={"code": code, "limit": 1})
        data = result.get("data") or []
        return data[0] if data else None

    # ----- issuing --------------------------------------------------------------------------

    def refund(
        self, *, payment_intent: str, amount: int, metadata: dict[str, str], idempotency_key: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/refunds",
            data={
                "payment_intent": payment_intent,
                "amount": amount,
                "reason": "requested_by_customer",
                **{f"metadata[{k}]": v for k, v in metadata.items()},
            },
            idempotency_key=idempotency_key,
        )

    def credit_customer(
        self,
        *,
        customer: str,
        amount: int,
        currency: str,
        description: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/customers/{customer}/balance_transactions",
            data={
                "amount": -amount,  # negative = credit
                "currency": currency.lower(),
                "description": description[:350],
                **{f"metadata[{k}]": v for k, v in metadata.items()},
            },
            idempotency_key=idempotency_key,
        )

    def voucher(
        self,
        *,
        amount: int,
        currency: str,
        code: str,
        customer: str | None,
        expires_at: int | None,
        name: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """A single-use coupon and a promotion code for it (restricted to the customer if known)."""
        coupon = self._request(
            "POST",
            "/v1/coupons",
            data={
                "amount_off": amount,
                "currency": currency.lower(),
                "duration": "once",
                "max_redemptions": 1,
                "name": name[:40],
                **{f"metadata[{k}]": v for k, v in metadata.items()},
            },
            idempotency_key=f"{idempotency_key}:coupon",
        )
        promo_data: dict[str, Any] = {
            "promotion[type]": "coupon",
            "promotion[coupon]": coupon["id"],
            "code": code,
            "max_redemptions": 1,
            **{f"metadata[{k}]": v for k, v in metadata.items()},
        }
        if customer:
            promo_data["customer"] = customer
        if expires_at:
            promo_data["expires_at"] = expires_at
        promo = self._request(
            "POST",
            "/v1/promotion_codes",
            data=promo_data,
            idempotency_key=f"{idempotency_key}:promo",
        )
        return coupon, promo
