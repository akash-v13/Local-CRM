"""Talking to a Shopify store's Admin GraphQL API.

Checked against shopify.dev (API version 2026-10, October 2026):

- Endpoint: POST https://<shop>.myshopify.com/admin/api/2026-10/graphql.json
  with the header `X-Shopify-Access-Token` (see app/connectors/auth.py for how the
  token is made: the client credentials grant, a 24-hour token, cached).
- Errors usually come back as HTTP 200 with `errors[].extensions.code`:
  THROTTLED (cost limit; retry), ACCESS_DENIED (a missing scope, or protected customer
  data not granted), INTERNAL_SERVER_ERROR. Real HTTP errors: 401 (bad token),
  402 (store frozen), 403, 404 (no such store), 423 (store locked), 5xx.
- Mutations report problems in `userErrors {field message}`.
- `refundCreate` requires an `@idempotent(key:)` directive (mandatory since 2026-04):
  the same key never refunds twice. `storeCreditAccountCredit` and
  `discountCodeBasicCreate` have no idempotency key: discount codes are unique per
  store (a retry finds the code it made), and store credit is never retried when the
  outcome is unknown (see services/payouts.py).
- `Customer.email` is deprecated: `defaultEmailAddress { emailAddress }`.
- `Order.fulfillments` is a list (not a connection); `trackingInfo` too.

Every operation is named `Lcrm…` so logs (and the local mock) can tell them apart.
"""

import re
from collections.abc import Callable
from typing import Any

import httpx

API_VERSION = "2026-10"
SHOP_DOMAIN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$")
TIMEOUT_SECONDS = 20.0

# force_refresh -> request headers (X-Shopify-Access-Token). See AuthProvider.headers_for.
HeadersSource = Callable[[bool], dict[str, str]]


def shop_base_url(shop: str, override: str = "") -> str:
    """https://<shop>, or <override>/<shop> for the local mock API."""
    if override:
        return f"{override.rstrip('/')}/{shop}"
    return f"https://{shop}"


def gid_number(gid: str | None) -> str:
    """gid://shopify/Order/5512 -> "5512" (for admin links)."""
    return (gid or "").rsplit("/", 1)[-1]


class ShopifyError(Exception):
    """A Shopify call failed.

    retryable:       worth trying again later (network, throttling, 5xx).
    outcome_unknown: the request may have been carried out (timeout after sending, 5xx).
    code:            Shopify's error code when there is one (THROTTLED, TAKEN, …).
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        outcome_unknown: bool = False,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        self.code = code


HTTP_ERRORS = {
    401: "Shopify rejected the app's access token. Check the Shopify credential.",
    402: "The Shopify store is frozen (an unpaid Shopify bill).",
    403: "Shopify refused the request. Check the app's access scopes.",
    404: "No Shopify store at that address. Check the shop domain (….myshopify.com).",
    423: "The Shopify store is locked.",
}


class ShopifyClient:
    def __init__(
        self,
        http: httpx.Client,
        shop: str,
        headers: HeadersSource,
        base_override: str = "",
    ) -> None:
        self.http = http
        self.shop = shop
        self.headers = headers
        self.url = f"{shop_base_url(shop, base_override)}/admin/api/{API_VERSION}/graphql.json"

    def graphql(self, operation: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Run one named operation; returns `data`. Raises ShopifyError."""
        for attempt in (1, 2):
            headers = {**self.headers(attempt == 2), "Content-Type": "application/json"}
            try:
                response = self.http.post(
                    self.url,
                    json={"query": query, "variables": variables, "operationName": operation},
                    headers=headers,
                    timeout=TIMEOUT_SECONDS,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Never reached Shopify: safe to try again.
                raise ShopifyError(
                    f"Couldn't reach Shopify ({type(exc).__name__}).", retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                raise ShopifyError(
                    f"Shopify didn't answer ({type(exc).__name__}).",
                    retryable=True,
                    outcome_unknown=True,
                ) from exc
            if response.status_code == 401 and attempt == 1:
                continue  # the token may have just expired: get a new one, once
            break
        status = response.status_code
        if status in HTTP_ERRORS:
            raise ShopifyError(HTTP_ERRORS[status], retryable=False)
        if status == 429:
            raise ShopifyError("Shopify is rate limiting requests.", retryable=True)
        if status >= 500:
            raise ShopifyError(
                f"Shopify had an internal error (HTTP {status}).",
                retryable=True,
                outcome_unknown=True,
            )
        if status >= 400:
            raise ShopifyError(f"Shopify returned HTTP {status}.", retryable=False)
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ShopifyError("Shopify's response isn't JSON.", retryable=False) from exc
        errors = body.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else {"message": errors}
            code = (first.get("extensions") or {}).get("code")
            message = first.get("message") or str(code)
            if code == "THROTTLED":
                raise ShopifyError("Shopify's API limit was reached.", retryable=True, code=code)
            if code == "INTERNAL_SERVER_ERROR":
                raise ShopifyError(
                    "Shopify had an internal error.",
                    retryable=True,
                    outcome_unknown=True,
                    code=code,
                )
            if code == "ACCESS_DENIED":
                raise ShopifyError(
                    f"The Shopify app isn't allowed to do this: {message} Check its access "
                    "scopes (and protected customer data access) in the Dev Dashboard.",
                    retryable=False,
                    code=code,
                )
            raise ShopifyError(f"Shopify: {message}", retryable=False, code=code)
        data: dict[str, Any] = body.get("data") or {}
        return data

    @staticmethod
    def _user_errors(payload: dict[str, Any]) -> None:
        problems = payload.get("userErrors") or []
        if problems:
            message = "; ".join(p.get("message", "") for p in problems)
            code = next((p.get("code") for p in problems if p.get("code")), None)
            raise ShopifyError(f"Shopify: {message}", retryable=False, code=code)

    # ----- reading ---------------------------------------------------------------------------

    def shop_info(self) -> dict[str, Any]:
        data = self.graphql(
            "LcrmShop", "query LcrmShop { shop { name currencyCode myshopifyDomain } }", {}
        )
        shop: dict[str, Any] = data["shop"]
        return shop

    def find_orders(self, search: str, first: int = 5) -> list[dict[str, Any]]:
        """Orders matching a search like "name:#1001" or "email:x@y.com", newest first."""
        data = self.graphql("LcrmOrders", ORDERS_QUERY, {"query": search, "first": first})
        nodes: list[dict[str, Any]] = (data.get("orders") or {}).get("nodes") or []
        return nodes

    def order_payments(self, order_id: str) -> dict[str, Any] | None:
        """An order's payment transactions and refunds (to refund it, or find our refund)."""
        data = self.graphql("LcrmOrderPayments", ORDER_PAYMENTS_QUERY, {"id": order_id})
        order: dict[str, Any] | None = data.get("order")
        return order

    def discount_by_code(self, code: str) -> dict[str, Any] | None:
        data = self.graphql("LcrmDiscountByCode", DISCOUNT_BY_CODE_QUERY, {"code": code})
        node: dict[str, Any] | None = data.get("codeDiscountNodeByCode")
        return node

    # ----- issuing ---------------------------------------------------------------------------

    def refund(
        self,
        *,
        order_id: str,
        parent_id: str,
        gateway: str,
        amount: str,
        note: str,
        notify: bool,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Refund an amount (not line items) to the order's original payment."""
        data = self.graphql(
            "LcrmRefund",
            REFUND_MUTATION,
            {
                "key": idempotency_key[:255],
                "input": {
                    "orderId": order_id,
                    "note": note,
                    "notify": notify,
                    "transactions": [
                        {
                            "orderId": order_id,
                            "parentId": parent_id,
                            "gateway": gateway,
                            "kind": "REFUND",
                            "amount": amount,
                        }
                    ],
                },
            },
        )
        payload = data.get("refundCreate") or {}
        self._user_errors(payload)
        refund: dict[str, Any] = payload["refund"]
        return refund

    def store_credit(
        self,
        *,
        customer_id: str,
        amount: str,
        currency: str,
        expires_at: str | None,
        notify: bool,
    ) -> dict[str, Any]:
        """Credit the customer's store credit account (created if needed). NOT idempotent."""
        credit: dict[str, Any] = {
            "creditAmount": {"amount": amount, "currencyCode": currency},
            "notify": notify,
        }
        if expires_at:
            credit["expiresAt"] = expires_at
        data = self.graphql(
            "LcrmStoreCredit", STORE_CREDIT_MUTATION, {"id": customer_id, "creditInput": credit}
        )
        payload = data.get("storeCreditAccountCredit") or {}
        self._user_errors(payload)
        transaction: dict[str, Any] = payload["storeCreditAccountTransaction"]
        return transaction

    def discount_code(
        self,
        *,
        code: str,
        title: str,
        amount: str,
        customer_id: str | None,
        starts_at: str,
        ends_at: str | None,
    ) -> dict[str, Any]:
        """A single-use, fixed-amount discount code (only for the customer when known)."""
        discount: dict[str, Any] = {
            "title": title[:255],
            "code": code,
            "startsAt": starts_at,
            "usageLimit": 1,
            "appliesOncePerCustomer": True,
            "customerGets": {
                "value": {"discountAmount": {"amount": amount, "appliesOnEachItem": False}},
                "items": {"all": True},
            },
        }
        if customer_id:  # otherwise it works for anyone with the code (still single use)
            discount["context"] = {"customers": {"add": [customer_id]}}
        if ends_at:
            discount["endsAt"] = ends_at
        data = self.graphql("LcrmDiscount", DISCOUNT_MUTATION, {"discount": discount})
        payload = data.get("discountCodeBasicCreate") or {}
        self._user_errors(payload)
        node: dict[str, Any] = payload["codeDiscountNode"]
        return node


ORDERS_QUERY = """
query LcrmOrders($query: String!, $first: Int!) {
  orders(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) {
    nodes {
      id
      name
      createdAt
      cancelledAt
      displayFinancialStatus
      displayFulfillmentStatus
      currencyCode
      presentmentCurrencyCode
      totalPriceSet { shopMoney { amount currencyCode } }
      totalRefundedSet { shopMoney { amount currencyCode } }
      tags
      customer {
        id
        numberOfOrders
        amountSpent { amount currencyCode }
        defaultEmailAddress { emailAddress }
      }
      fulfillments(first: 5) {
        createdAt
        displayStatus
        estimatedDeliveryAt
        inTransitAt
        deliveredAt
        trackingInfo(first: 1) { number company url }
      }
    }
  }
}
"""

ORDER_PAYMENTS_QUERY = """
query LcrmOrderPayments($id: ID!) {
  order(id: $id) {
    id
    name
    presentmentCurrencyCode
    transactions(first: 20) {
      id
      kind
      status
      gateway
      amountSet { presentmentMoney { amount currencyCode } }
    }
    refunds(first: 50) {
      id
      note
      totalRefundedSet { presentmentMoney { amount currencyCode } }
    }
  }
}
"""

DISCOUNT_BY_CODE_QUERY = """
query LcrmDiscountByCode($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount { ... on DiscountCodeBasic { title } }
  }
}
"""

REFUND_MUTATION = """
mutation LcrmRefund($input: RefundInput!, $key: String!) {
  refundCreate(input: $input) @idempotent(key: $key) {
    refund { id note totalRefundedSet { presentmentMoney { amount currencyCode } } }
    userErrors { field message }
  }
}
"""

STORE_CREDIT_MUTATION = """
mutation LcrmStoreCredit($id: ID!, $creditInput: StoreCreditAccountCreditInput!) {
  storeCreditAccountCredit(id: $id, creditInput: $creditInput) {
    storeCreditAccountTransaction {
      amount { amount currencyCode }
      account { id balance { amount currencyCode } }
    }
    userErrors { field message }
  }
}
"""

DISCOUNT_MUTATION = """
mutation LcrmDiscount($discount: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $discount) {
    codeDiscountNode { id }
    userErrors { field code message }
  }
}
"""
