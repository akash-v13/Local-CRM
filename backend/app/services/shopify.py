"""The business's Shopify store: connecting it, and looking up a case's order.

Order lookup runs as the first enrichment step (services/enrichment.py) when the
store is connected: by the order number on the case, or else the customer's
latest order by email. The fields are saved as enrichment.shopify.<field>, so
routing, compensation rules, AI templates and connectors can use them.

Issuing compensation through Shopify (refunds, store credit, discount codes) is in
services/payouts.py, next to Stripe.

Credentials: a "shopify" credential holds the shop domain and the Dev Dashboard
app's client ID + secret. The 24-hour access token is generated, cached and
refreshed by app/connectors/auth.py (AuthProvider), like other token credentials.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.connectors.auth import AuthProvider, CredentialError
from app.connectors.runner_settings import RunSettings
from app.domain.errors import ConflictError, NotFoundError
from app.models import Credential, Tenant
from app.repositories import CaseRepository, MessageRepository, TenantRepository
from app.schemas import (
    CredentialWrite,
    ShopifyCheckResult,
    ShopifyConnectRequest,
    ShopifyInfo,
    ShopifyLookupRequest,
    ShopifyLookupResult,
    ShopifySettingsData,
)
from app.security.ssrf import Resolver
from app.services.connectors import run_settings
from app.services.credentials import CredentialService
from app.services.routing import case_context
from app.shopify.client import ShopifyClient, ShopifyError, gid_number
from app.shopify.orders import (
    SHOPIFY_FIELDS,
    email_search,
    order_fields,
    order_search,
    same_order_name,
)

STEP_KEY = "shopify"  # enrichment.shopify.<field>
STEP_NAME = "Shopify order"
FIELD_LABELS = {**SHOPIFY_FIELDS, "emailMatches": "Order email matches the customer's"}


def settings_of(tenant: Tenant) -> ShopifySettingsData:
    return ShopifySettingsData.model_validate(tenant.shopify_settings or {})


def client_for(
    session_factory: sessionmaker[Session],
    http: httpx.Client,
    settings: RunSettings,
    credential: Credential,
) -> ShopifyClient:
    """A client for the credential's store. Tokens come from (and are cached by) AuthProvider."""
    provider = AuthProvider(session_factory, http, settings)
    credential_id = credential.id

    def headers(force_refresh: bool) -> dict[str, str]:
        try:
            return provider.headers_for(credential_id, force_refresh=force_refresh).headers
        except CredentialError as exc:
            raise ShopifyError(
                f"Couldn't get a Shopify access token: {exc}", retryable=False
            ) from exc

    return ShopifyClient(http, credential.config["shop"], headers, settings.shopify_api_base)


def admin_order_url(shop: str, order_id: str | None) -> str | None:
    return f"https://{shop}/admin/orders/{gid_number(order_id)}" if order_id else None


def lookup_order(
    client: ShopifyClient,
    settings: ShopifySettingsData,
    *,
    order_number: Any,
    email: str | None,
    now: datetime | None = None,
) -> ShopifyLookupResult:
    """Find the case's order. Never guesses: an order number that isn't found is an error,
    not a reason to fall back to some other order of the customer's."""
    started = time.monotonic()
    searched: list[str] = []
    now = now or datetime.now(UTC)

    def done(**kwargs: Any) -> ShopifyLookupResult:
        return ShopifyLookupResult(
            searched=searched, duration_ms=int((time.monotonic() - started) * 1000), **kwargs
        )

    try:
        wanted = str(order_number).strip() if order_number not in (None, "") else ""
        search = order_search(wanted) if wanted else None
        if search:
            searched.append(search)
            orders = [o for o in client.find_orders(search) if same_order_name(o["name"], wanted)]
            if not orders:
                return done(status="failed", error=f"No Shopify order {wanted}.")
            order, matched_by = orders[0], "order number"
        elif email and settings.match_by_email:
            search = email_search(email)
            searched.append(search)
            orders = client.find_orders(search, first=1)
            if not orders:
                return done(status="skipped", error="No Shopify orders for this email address.")
            order, matched_by = orders[0], "email (latest order)"
        else:
            return done(status="skipped", error="No order number on the case.")
    except ShopifyError as exc:
        return done(status="failed", error=str(exc))

    fields = order_fields(order, now=now, matched_by=matched_by)
    if email:
        # Someone could quote another person's order number: rules can require a match,
        # and refunds / store credit through Shopify are refused without one.
        order_email = ((order.get("customer") or {}).get("defaultEmailAddress") or {}).get(
            "emailAddress"
        ) or ""
        fields["emailMatches"] = order_email.strip().lower() == email.strip().lower()
    return done(status="ok", fields=fields, admin_url=admin_order_url(client.shop, order.get("id")))


class ShopifyService:
    def __init__(
        self,
        session: Session,
        *,
        http: httpx.Client,
        settings: Settings,
        resolve: Resolver,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.session = session
        self.http = http
        self.run_settings = run_settings(settings, resolve)
        self.session_factory = session_factory
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def _credential(self, tenant_id: uuid.UUID, credential_id: uuid.UUID | None) -> Credential:
        credential = self.session.get(Credential, credential_id) if credential_id else None
        if credential is None or credential.tenant_id != tenant_id:
            raise ConflictError("Connect the Shopify store first (Operations → Shopify).")
        if credential.kind != "shopify":
            raise ConflictError(f"'{credential.name}' isn't a Shopify credential.")
        return credential

    def info(self, tenant_id: uuid.UUID) -> ShopifyInfo:
        settings = settings_of(self._tenant(tenant_id))
        shop = None
        if settings.credential_id:
            credential = self.session.get(Credential, settings.credential_id)
            if credential is not None and credential.tenant_id == tenant_id:
                shop = credential.config.get("shop")
        return ShopifyInfo(settings=settings, shop=shop, fields=FIELD_LABELS)

    def save_settings(self, tenant_id: uuid.UUID, data: ShopifySettingsData) -> ShopifyInfo:
        tenant = self._tenant(tenant_id)
        if data.credential_id is not None:
            self._credential(tenant_id, data.credential_id)
        tenant.shopify_settings = data.model_dump(mode="json")
        self.session.commit()
        return self.info(tenant_id)

    def connect(self, tenant_id: uuid.UUID, body: ShopifyConnectRequest) -> ShopifyCheckResult:
        """Save the store's credential (new, or replacing the connected one), turn the
        lookup on, and check the connection."""
        tenant = self._tenant(tenant_id)
        settings = settings_of(tenant)
        write = CredentialWrite(
            name=f"Shopify: {body.shop}",
            kind="shopify",
            config={"shop": body.shop.lower()},
            secrets={"client_id": body.client_id, "client_secret": body.client_secret},
        )
        credentials = CredentialService(self.session)
        # Reconnecting (new secret, or another store) updates the store's credential.
        current = next(
            (
                c
                for c in credentials.list(tenant_id)
                if c.kind == "shopify"
                and (c.id == settings.credential_id or c.config.get("shop") == write.config["shop"])
            ),
            None,
        )
        if current is not None:
            credential = credentials.replace(tenant_id, current.id, write)
        else:
            credential = credentials.create(tenant_id, write)
        settings.credential_id, settings.enabled = credential.id, True
        tenant.shopify_settings = settings.model_dump(mode="json")
        self.session.commit()
        return self.check(tenant_id)

    def check(self, tenant_id: uuid.UUID) -> ShopifyCheckResult:
        """Get a token and read the shop's name: are the domain, ID and secret right?"""
        settings = settings_of(self._tenant(tenant_id))
        try:
            credential = self._credential(tenant_id, settings.credential_id)
            client = client_for(self.session_factory, self.http, self.run_settings, credential)
            shop = client.shop_info()
        except (ConflictError, ShopifyError) as exc:
            return ShopifyCheckResult(ok=False, detail=str(exc))
        return ShopifyCheckResult(
            ok=True,
            shop_name=shop.get("name"),
            currency=shop.get("currencyCode"),
            detail=f"Connected to {shop.get('name')} ({shop.get('myshopifyDomain')}).",
        )

    def lookup(self, tenant_id: uuid.UUID, body: ShopifyLookupRequest) -> ShopifyLookupResult:
        """Run the lookup now, for a case or an order number / email. Saves nothing."""
        settings = settings_of(self._tenant(tenant_id))
        credential = self._credential(tenant_id, settings.credential_id)
        if body.case_number is not None:
            case = self.cases.get_by_number(tenant_id, body.case_number)
            if case is None:
                raise NotFoundError(f"Case {body.case_number} not found.")
            texts = MessageRepository(self.session).customer_texts(tenant_id, case.id)
            order_number = case_context(case, texts).get(settings.order_field)
            email: str | None = case.customer.email
        else:
            order_number, email = body.order_number, body.email
        client = client_for(self.session_factory, self.http, self.run_settings, credential)
        return lookup_order(client, settings, order_number=order_number, email=email)


def shopify_step(session: Session, tenant: Tenant) -> tuple[ShopifySettingsData, Credential] | None:
    """The Shopify lookup step for enrichment, when the store is connected."""
    settings = settings_of(tenant)
    if not settings.enabled or settings.credential_id is None:
        return None
    credential = session.get(Credential, settings.credential_id)
    if credential is None or credential.tenant_id != tenant.id or credential.kind != "shopify":
        return None
    return settings, credential
