"""Issuing approved compensation through the business's Stripe account or Shopify store.

    compensation approved ──► payout queued ──► issue_payout job ──► Stripe / Shopify ──► case

- A payout is queued when a compensation decision becomes **approved** (automatically,
  or when someone approves it) and the business has payouts on with `auto_pay`; or
  when an agent clicks **Pay** on the case.
- One payout per decision: its idempotency key is derived from the case and the
  decision and is unique in the database. The same key goes to Stripe, so a retry of
  an in-flight request is replayed, not repeated.
- Methods: `stripe_refund` (back to the card the order was paid with), `stripe_credit`
  (customer balance for future invoices), `stripe_voucher` (single-use promotion code);
  `shopify_refund` (refund on the Shopify order, to its original payment), `shopify_credit`
  (the customer's Shopify store credit), `shopify_discount` (single-use discount code);
  `manual` types are left for a person.
- Shopify: refunds carry Shopify's mandatory idempotency key and a note naming the
  payout, so after an unclear error we find our own refund before trying again.
  Discount codes are unique per store, so a retry finds the code it made. Store credit
  has no idempotency key: it's never retried automatically when the outcome is unknown,
  and asks a person to check Shopify first. Refunds and store credit also require the
  order's email to match the customer's (someone could quote another person's order).
- The worker calls Stripe with no database session open. Network errors, 429s and
  5xx retry with backoff; other Stripe errors fail at once with Stripe's message.
  A failed payout can be retried from the case after fixing the cause (e.g. the
  payment wasn't found): that uses a new key, since Stripe replays failures too.
- On success the case's decision records the payout; for vouchers its label gains the
  code (e.g. "Voucher code SORRY-K7Q2MX worth USD 15.00…") so AI drafts can quote it.
"""

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.auth import load_secrets
from app.connectors.runner_settings import RunSettings
from app.domain.errors import ConflictError, NotFoundError
from app.models import Case, CaseEvent, Credential, Job, Payout, Tenant
from app.models.base import utcnow
from app.payouts.stripe import StripeClient, StripeError, to_minor
from app.repositories import CaseRepository, MessageRepository, TenantRepository
from app.schemas import PayoutListRow, PayoutRead, PayoutSettingsData, StripeCheckResult
from app.services.routing import case_context
from app.services.shopify import STEP_KEY as SHOPIFY_KEY
from app.services.shopify import client_for as shopify_client_for
from app.services.shopify import lookup_order, shopify_step
from app.shopify.client import ShopifyClient, ShopifyError

PAYOUT_ATTEMPTS = 5
VOUCHER_METHODS = ("stripe_voucher", "shopify_discount")
REFUND_METHODS = ("stripe_refund", "shopify_refund")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to read out


def settings_of(tenant: Tenant) -> PayoutSettingsData:
    return PayoutSettingsData.model_validate(tenant.payout_settings or {})


def method_for(settings: PayoutSettingsData, kind: str | None) -> str | None:
    """The method a compensation type is issued with, or None (manual / payouts off)."""
    if not settings.enabled or not kind:
        return None
    method = settings.methods.get(kind)
    return None if method in (None, "manual") else method


def voucher_code(prefix: str, seed: str) -> str:
    """Stable for a payout (retries must send identical parameters to Stripe)."""
    digest = hashlib.sha256(seed.encode()).digest()
    return prefix + "-" + "".join(CODE_ALPHABET[b % len(CODE_ALPHABET)] for b in digest[:6])


def stripe_key(session: Session, tenant_id: uuid.UUID, credential_id: uuid.UUID | None) -> str:
    """The Stripe secret key from the business's credential (decrypted; never log it)."""
    credential = session.get(Credential, credential_id) if credential_id else None
    if credential is None or credential.tenant_id != tenant_id:
        raise ConflictError("Choose the Stripe credential under Operations → Payouts.")
    secrets = load_secrets(credential)
    key = secrets.get("token") or secrets.get("key")
    if not key:
        raise ConflictError(
            f"The credential '{credential.name}' has no secret key. "
            "Use a 'Bearer token' credential."
        )
    return key


# ----- queueing --------------------------------------------------------------------------


def queue_payout(
    session: Session, case: Case, actor_id: str | None, *, manual: bool = False
) -> Payout | None:
    """Queue a payout for the case's approved compensation if the business issues this
    type automatically (or `manual`: an agent clicked Pay). Does NOT commit."""
    tenant = session.get(Tenant, case.tenant_id)
    decision = dict(case.decisions.get("compensation") or {})
    if tenant is None or decision.get("status") != "approved" or not decision.get("amount"):
        if manual:
            raise ConflictError("Only approved compensation with an amount can be paid.")
        return None
    settings = settings_of(tenant)
    method = method_for(settings, decision.get("type"))
    if method is None:
        if manual:
            raise ConflictError(
                f"{decision.get('type')} isn't issued through a payment provider "
                "(see Operations → Payouts)."
            )
        return None
    if not settings.auto_pay and not manual:
        return None

    base_key = f"lcrm:{case.id}:{decision.get('decided_at')}"
    existing = session.scalars(
        select(Payout)
        .where(Payout.idempotency_key.startswith(base_key))
        .order_by(Payout.created_at.desc())
    ).first()
    if existing is not None and existing.status != "failed":
        if manual:
            raise ConflictError(f"This compensation is already {existing.status}.")
        return None
    round_ = (existing.details.get("round", 0) + 1) if existing else 0
    key = base_key if round_ == 0 else f"{base_key}:retry{round_}"
    details: dict[str, Any] = {"round": round_}
    if method in VOUCHER_METHODS:
        details["code"] = voucher_code(settings.voucher_prefix, key)
        if settings.voucher_expiry_days:
            details["expires_at"] = int(
                (utcnow() + timedelta(days=settings.voucher_expiry_days)).timestamp()
            )
    payout = Payout(
        tenant_id=case.tenant_id,
        case_id=case.id,
        kind=str(decision.get("type")),
        provider="shopify" if method.startswith("shopify_") else "stripe",
        method=method,
        amount=float(decision["amount"]),
        currency=str(decision.get("currency") or "USD").upper(),
        status="queued",
        idempotency_key=key,
        details=details,
        attempts=0,
        created_by=actor_id or "system",
    )
    session.add(payout)
    session.flush()
    session.add(
        Job(
            tenant_id=case.tenant_id,
            kind="issue_payout",
            case_id=case.id,
            payload={"payout_id": str(payout.id)},
            max_attempts=PAYOUT_ATTEMPTS,
        )
    )
    _record_on_decision(case, payout)
    session.add(
        CaseEvent(
            tenant_id=case.tenant_id,
            case_id=case.id,
            event_type="payout.queued",
            actor_type="human" if actor_id else "system",
            actor_id=actor_id,
            data={"method": method, "amount": payout.amount, "currency": payout.currency},
        )
    )
    return payout


def _record_on_decision(case: Case, payout: Payout) -> None:
    decision = dict(case.decisions.get("compensation") or {})
    decision["payout"] = {
        "id": str(payout.id),
        "status": payout.status,
        "method": payout.method,
        "external_id": payout.external_id,
        "code": payout.details.get("code") if payout.status == "succeeded" else None,
        "error": payout.error,
    }
    if payout.status == "succeeded" and payout.method in VOUCHER_METHODS:
        expires = payout.details.get("expires_on")
        decision["label"] = (
            f"Voucher code {payout.details['code']} worth {payout.currency} {payout.amount:.2f}"
            f" (single use{f', valid until {expires}' if expires else ''})"
        )
    elif payout.status == "succeeded" and payout.method in REFUND_METHODS:
        decision["label"] = (
            f"Refund of {payout.currency} {payout.amount:.2f} (issued to the original payment)"
        )
    elif payout.status == "succeeded" and payout.method == "shopify_credit":
        decision["label"] = (
            f"Store credit of {payout.currency} {payout.amount:.2f} "
            "(added to the customer's account)"
        )
    case.decisions = {**case.decisions, "compensation": decision}


# ----- issuing (worker) ------------------------------------------------------------------


def issue_payout_job(
    session_factory: sessionmaker[Session],
    http: httpx.Client,
    stripe_base: str,
    job_id: uuid.UUID,
    shopify: RunSettings | None = None,
) -> None:
    """Worker handler for `issue_payout`. Raises StripeError / ShopifyError for retryable
    failures (the job queue retries with backoff). `shopify`: how to reach Shopify stores
    (token caching, mock API base) for shopify_* methods."""
    with session_factory() as session:
        job = session.get(Job, job_id)
        payout = session.get(Payout, uuid.UUID(job.payload["payout_id"])) if job else None
        case = session.get(Case, payout.case_id) if payout else None
        tenant = session.get(Tenant, payout.tenant_id) if payout else None
        if job is None or payout is None or case is None or tenant is None:
            return
        if payout.status == "succeeded":  # already done: never pay twice
            job.status = "done"
            session.commit()
            return
        settings = settings_of(tenant)
        on_shopify = payout.method.startswith("shopify_")
        key = ""
        shop = shopify_step(session, tenant) if on_shopify else None
        try:
            if on_shopify and (shop is None or shopify is None):
                raise ConflictError("Shopify isn't connected (Operations → Shopify).")
            if not on_shopify:
                key = stripe_key(session, tenant.id, settings.credential_id)
        except ConflictError as exc:
            _finish(session, job, payout, case, error=str(exc))
            session.commit()
            return
        found = case.enrichment.get(SHOPIFY_KEY) or {}
        shopify_order = dict(found.get("data") or {}) if found.get("status") == "ok" else {}
        texts = MessageRepository(session).customer_texts(case.tenant_id, case.id)
        context = case_context(case, texts)
        email = case.customer.email
        payout.status, payout.attempts = "processing", payout.attempts + 1
        session.commit()
        round_ = int(payout.details.get("unknown_outcomes", 0))
        plan = {
            "payout_id": str(payout.id),
            "check_first": round_ > 0,  # an earlier attempt may have succeeded (5xx)
            "method": payout.method,
            "amount": payout.amount,
            "currency": payout.currency,
            # Stripe replays a 500 for the same key, so each unknown outcome moves to a new key.
            "key": payout.idempotency_key + (f":u{round_}" if round_ else ""),
            "details": dict(payout.details),
            "case_number": case.case_number,
            "payment_id": context.get(settings.payment_field) if settings.payment_field else None,
            "order": context.get(settings.order_field),
            "shopify_order": shopify_order,
            "shopify_order_number": context.get(shop[0].order_field) if shop else None,
        }
        payout_id = payout.id

    # No database session open from here.
    try:
        if shop is not None and shopify is not None:
            client = shopify_client_for(session_factory, http, shopify, shop[1])
            external_id, details = _call_shopify(client, plan, shop[0], email)
            mode = "shopify"
        else:
            stripe = StripeClient(http, key, stripe_base)
            external_id, details = _call_stripe(stripe, plan, settings, email)
            mode = stripe.mode
    except (StripeError, ShopifyError) as exc:
        with session_factory() as session:
            payout = session.get(Payout, payout_id)
            job = session.get(Job, job_id)
            case = session.get(Case, payout.case_id) if payout else None
            assert payout is not None and job is not None and case is not None
            if exc.retryable and job.attempts < job.max_attempts:
                payout.status, payout.error = "retrying", str(exc)
                if exc.outcome_unknown:
                    unknown = int(payout.details.get("unknown_outcomes", 0)) + 1
                    payout.details = {**payout.details, "unknown_outcomes": unknown}
                _record_on_decision(case, payout)
                session.commit()
                raise
            _finish(session, job, payout, case, error=str(exc))
            session.commit()
        return

    with session_factory() as session:
        payout = session.get(Payout, payout_id)
        job = session.get(Job, job_id)
        case = session.get(Case, payout.case_id) if payout else None
        assert payout is not None and job is not None and case is not None
        payout.external_id = external_id
        payout.details = {**payout.details, **details, "mode": mode}
        _finish(session, job, payout, case, error=None)
        session.commit()


def _call_stripe(
    client: StripeClient, plan: dict[str, Any], settings: PayoutSettingsData, email: str
) -> tuple[str, dict[str, Any]]:
    amount = to_minor(plan["amount"], plan["currency"])
    metadata = {
        "case_number": str(plan["case_number"]),
        "payout_id": plan["payout_id"],
        "source": "local-crm",
    }
    method = plan["method"]
    if method == "stripe_refund":
        payment = plan["payment_id"]
        if not payment and settings.metadata_key and plan["order"]:
            payment = client.find_payment_by_metadata(settings.metadata_key, str(plan["order"]))
        if not payment:
            raise StripeError(
                "Couldn't find the Stripe payment for order "
                f"{plan['order'] or '(no order number)'}.",
                retryable=False,
            )
        intent = client.payment_intent(str(payment))
        if str(intent.get("currency", "")).upper() != plan["currency"]:
            raise StripeError(
                f"The payment was in {str(intent.get('currency')).upper()}, "
                f"the refund in {plan['currency']}.",
                retryable=False,
            )
        found = client.find_refund(str(payment), plan["payout_id"]) if plan["check_first"] else None
        refund = found or client.refund(
            payment_intent=str(payment),
            amount=amount,
            metadata=metadata,
            idempotency_key=plan["key"],
        )
        return str(refund["id"]), {
            "payment_intent": payment,
            "provider_status": refund.get("status"),
        }
    customer = client.find_customer(email)
    if method == "stripe_credit":
        if not customer:
            raise StripeError(f"No Stripe customer has the email {email}.", retryable=False)
        found = client.find_credit(customer, plan["payout_id"]) if plan["check_first"] else None
        txn = found or client.credit_customer(
            customer=customer,
            amount=amount,
            currency=plan["currency"],
            description=f"Goodwill credit for case {plan['case_number']}",
            metadata=metadata,
            idempotency_key=plan["key"],
        )
        return str(txn["id"]), {"customer": customer, "ending_balance": txn.get("ending_balance")}
    if method == "stripe_voucher":
        details = plan["details"]
        existing = client.find_promotion_code(details["code"]) if plan["check_first"] else None
        if existing is not None:
            coupon = {"id": (existing.get("promotion") or {}).get("coupon")}
            promo = existing
        else:
            coupon, promo = client.voucher(
                amount=amount,
                currency=plan["currency"],
                code=details["code"],
                customer=customer,
                expires_at=details.get("expires_at"),
                name=f"Case {plan['case_number']}",
                metadata=metadata,
                idempotency_key=plan["key"],
            )
        expires = details.get("expires_at")
        expires_on = datetime.fromtimestamp(expires, UTC).date().isoformat() if expires else None
        return str(promo["id"]), {
            "coupon": coupon["id"],
            "customer": customer,
            "expires_on": expires_on,
        }
    raise StripeError(f"Unknown payout method {method}.", retryable=False)


def _call_shopify(
    client: ShopifyClient, plan: dict[str, Any], settings: Any, email: str
) -> tuple[str, dict[str, Any]]:
    """Issue on the business's Shopify store. `settings`: ShopifySettingsData."""
    order = plan["shopify_order"]
    if not order.get("orderId"):
        # Not looked up at intake (e.g. connected later): look it up now.
        found = lookup_order(
            client, settings, order_number=plan["shopify_order_number"], email=email
        )
        if found.status != "ok":
            raise ShopifyError(found.error or "No Shopify order for this case.", retryable=False)
        order = found.fields
    method, payout_id = plan["method"], plan["payout_id"]
    amount = f"{plan['amount']:.2f}"
    currency = plan["currency"]
    note = f"Local CRM case {plan['case_number']} (payout {payout_id})"
    if method in ("shopify_refund", "shopify_credit") and order.get("emailMatches") is False:
        raise ShopifyError(
            f"Order {order.get('orderNumber')} belongs to a different email address than the "
            "customer's. Check it, then issue this by hand.",
            retryable=False,
        )

    if method == "shopify_refund":
        payments = client.order_payments(order["orderId"])
        if payments is None:
            raise ShopifyError(
                f"Shopify order {order.get('orderNumber')} is gone.", retryable=False
            )
        if plan["check_first"]:  # an earlier attempt may have refunded already
            earlier = next(
                (r for r in payments.get("refunds") or [] if payout_id in (r.get("note") or "")),
                None,
            )
            if earlier is not None:
                return str(earlier["id"]), {
                    "order": payments.get("name"),
                    "order_id": order["orderId"],
                    "shop": client.shop,
                }
        if str(payments.get("presentmentCurrencyCode") or currency).upper() != currency:
            raise ShopifyError(
                f"The order was paid in {payments.get('presentmentCurrencyCode')}, "
                f"the refund is in {currency}.",
                retryable=False,
            )
        paid = [
            t
            for t in payments.get("transactions") or []
            if t.get("status") == "SUCCESS" and t.get("kind") in ("SALE", "CAPTURE")
        ]
        if not paid:
            raise ShopifyError(
                f"Order {payments.get('name')} has no captured payment to refund.", retryable=False
            )
        parent = paid[-1]
        refund = client.refund(
            order_id=order["orderId"],
            parent_id=str(parent["id"]),
            gateway=str(parent.get("gateway") or ""),
            amount=amount,
            note=note,
            notify=settings.notify_customer,
            idempotency_key=plan["key"],
        )
        return str(refund["id"]), {
            "order": payments.get("name"),
            "order_id": order["orderId"],
            "gateway": parent.get("gateway"),
            "shop": client.shop,
        }

    if method == "shopify_credit":
        customer = order.get("customerId")
        if not customer:
            raise ShopifyError("The order has no Shopify customer to credit.", retryable=False)
        if order.get("currency") and str(order["currency"]).upper() != currency:
            raise ShopifyError(
                f"The store's currency is {order['currency']}, the credit is in {currency}.",
                retryable=False,
            )
        expires = (
            (utcnow() + timedelta(days=settings.store_credit_expiry_days)).isoformat()
            if settings.store_credit_expiry_days
            else None
        )
        try:
            txn = client.store_credit(
                customer_id=customer,
                amount=amount,
                currency=currency,
                expires_at=expires,
                notify=settings.notify_customer,
            )
        except ShopifyError as exc:
            if exc.outcome_unknown:  # no idempotency key: never retry blindly
                raise ShopifyError(
                    f"{exc} Shopify may or may not have added the credit: check the customer's "
                    "store credit in Shopify before clicking Try again.",
                    retryable=False,
                ) from exc
            raise
        account = txn.get("account") or {}
        return str(account.get("id") or customer), {
            "customer": customer,
            "shop": client.shop,
            "balance": (account.get("balance") or {}).get("amount"),
        }

    if method == "shopify_discount":
        details = plan["details"]
        code, tag = details["code"], payout_id[:8]
        title = f"Local CRM case {plan['case_number']} ({tag})"

        def ours() -> dict[str, Any] | None:
            node = client.discount_by_code(code)
            found_title = ((node or {}).get("codeDiscount") or {}).get("title") or ""
            return node if node and tag in found_title else None

        expires = details.get("expires_at")
        expires_on = datetime.fromtimestamp(expires, UTC).date().isoformat() if expires else None
        existing = ours() if plan["check_first"] else None
        if existing is None:
            if order.get("currency") and str(order["currency"]).upper() != currency:
                raise ShopifyError(
                    f"The store's currency is {order['currency']}, the code is in {currency}.",
                    retryable=False,
                )
            try:
                existing = client.discount_code(
                    code=code,
                    title=title,
                    amount=amount,
                    customer_id=order.get("customerId") if order.get("emailMatches") else None,
                    starts_at=utcnow().isoformat(),
                    ends_at=datetime.fromtimestamp(expires, UTC).isoformat() if expires else None,
                )
            except ShopifyError as exc:
                taken = exc.code == "TAKEN" or "taken" in str(exc).lower() or "unique" in str(exc)
                existing = ours() if taken else None
                if existing is None:
                    raise
        return str(existing["id"]), {"expires_on": expires_on, "shop": client.shop}

    raise ShopifyError(f"Unknown payout method {method}.", retryable=False)


def _finish(session: Session, job: Job, payout: Payout, case: Case, *, error: str | None) -> None:
    payout.status = "failed" if error else "succeeded"
    payout.error = error
    payout.completed_at = utcnow()
    job.status = "done"
    _record_on_decision(case, payout)
    session.add(
        CaseEvent(
            tenant_id=payout.tenant_id,
            case_id=payout.case_id,
            event_type=f"payout.{payout.status}",
            actor_type="system",
            reason=error,
            data={
                "method": payout.method,
                "amount": payout.amount,
                "currency": payout.currency,
                "externalId": payout.external_id,
                "code": payout.details.get("code") if not error else None,
            },
        )
    )


def payout_gave_up(session: Session, job: Job, error: str) -> None:
    """The last retry failed (e.g. Stripe unreachable for a long time)."""
    payout = session.get(Payout, uuid.UUID(job.payload["payout_id"]))
    case = session.get(Case, payout.case_id) if payout else None
    if payout is not None and case is not None and payout.status != "succeeded":
        _finish(session, job, payout, case, error=error.strip().splitlines()[-1][:300])


# ----- settings, listing, manual actions -----------------------------------------------------


class PayoutService:
    def __init__(self, session: Session, http: httpx.Client, stripe_base: str) -> None:
        self.session = session
        self.http = http
        self.stripe_base = stripe_base
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def get_settings(self, tenant_id: uuid.UUID) -> PayoutSettingsData:
        return settings_of(self._tenant(tenant_id))

    def save_settings(self, tenant_id: uuid.UUID, data: PayoutSettingsData) -> PayoutSettingsData:
        tenant = self._tenant(tenant_id)
        if data.credential_id is not None:
            credential = self.session.get(Credential, data.credential_id)
            if credential is None or credential.tenant_id != tenant_id:
                raise NotFoundError("That credential doesn't exist.")
        uses_shopify = any(m.startswith("shopify_") for m in data.methods.values())
        if data.enabled and uses_shopify and shopify_step(self.session, tenant) is None:
            raise ConflictError("Connect your Shopify store first (Operations → Shopify).")
        tenant.payout_settings = data.model_dump(mode="json")
        self.session.commit()
        return data

    def check_stripe(self, tenant_id: uuid.UUID, credential_id: uuid.UUID) -> StripeCheckResult:
        """Sign in to Stripe with the credential (GET /v1/balance): valid key? test or live?"""
        self._tenant(tenant_id)
        try:
            key = stripe_key(self.session, tenant_id, credential_id)
            account = StripeClient(self.http, key, self.stripe_base).account()
        except (ConflictError, StripeError) as exc:
            return StripeCheckResult(ok=False, detail=str(exc))
        mode = "live" if account.mode == "live" else "test"
        return StripeCheckResult(
            ok=True,
            mode=mode,
            detail=f"Connected to Stripe in {mode} mode"
            + (
                f" (balances in {', '.join(c.upper() for c in account.currencies)})."
                if account.currencies
                else "."
            ),
        )

    def list_payouts(self, tenant_id: uuid.UUID, status: str | None = None) -> list[PayoutListRow]:
        self._tenant(tenant_id)
        stmt = (
            select(Payout, Case)
            .join(Case, Case.id == Payout.case_id)
            .where(Payout.tenant_id == tenant_id)
        )
        if status:
            stmt = stmt.where(Payout.status == status)
        rows = self.session.execute(stmt.order_by(Payout.created_at.desc()).limit(100)).all()
        return [
            PayoutListRow(
                **PayoutRead.model_validate(p).model_dump(),
                case_number=case.case_number,
                customer_email=case.customer.email,
            )
            for p, case in rows
        ]

    def case_payouts(self, tenant_id: uuid.UUID, case_number: int) -> Sequence[Payout]:
        case = self._case(tenant_id, case_number)
        stmt = select(Payout).where(Payout.case_id == case.id).order_by(Payout.created_at.desc())
        return self.session.scalars(stmt).all()

    def pay_now(self, tenant_id: uuid.UUID, case_number: int, actor_id: str) -> Payout:
        """Issue (or retry after a failure) the case's approved compensation."""
        case = self._case(tenant_id, case_number)
        payout = queue_payout(self.session, case, actor_id, manual=True)
        assert payout is not None
        case.updated_at = utcnow()
        self.session.commit()
        return payout

    def _case(self, tenant_id: uuid.UUID, case_number: int) -> Case:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        return case
