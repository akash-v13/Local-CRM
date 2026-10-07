"""Getting a business set up, whatever it sells on, and one view of everything it connected.

Local CRM isn't tied to one platform. Email is the universal way in: a Shopify store's
contact form, a SHOP.COM seller account's "Contact seller" messages and a website's
contact form all arrive in a support inbox. Store platforms (Shopify today), payment
providers (Stripe) and the business's own systems (connectors) are optional extras.

- The **profile** (`tenants.profile`) records where the business sells: Shopify, a
  marketplace (SHOP.COM, Amazon, Etsy…), its own website, or in store. It only decides
  which setup steps and integrations are suggested; nothing is hidden or locked.
- The **setup checklist** is worked out from what's actually configured, so a step is
  ticked off when it's done anywhere in the app.
- Saving the profile switches on one sensible default when it isn't configured yet:
  reading order numbers out of emails (so lookups and rules work on email cases).
- **Integrations** are cards with a status, grouped as store platforms, messages,
  payments and the business's own systems.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.reading import PATTERN_PRESETS
from app.config import Settings
from app.domain.errors import NotFoundError
from app.models import Mailbox, Tenant
from app.repositories import (
    CompensationRuleRepository,
    ConnectorRepository,
    CredentialRepository,
    TenantRepository,
)
from app.schemas import (
    MARKETPLACES,
    BusinessProfile,
    IntegrationCard,
    IntegrationsInfo,
    PayoutSettingsData,
    ReadingField,
    ReadingSettingsData,
    SetupInfo,
    SetupStep,
    ShopifySettingsData,
)
from app.services.pipeline import reader_kind
from app.services.shopify import shopify_step

ORDER_FIELD = ReadingField(
    key="orderNumber",
    label="Order number",
    description="the order number of the order the customer is writing about now",
    pattern=PATTERN_PRESETS["order"][0],
)
READERS = {"jev": "Jev (TypeSafe AI)", "claude": "Claude", "patterns": "patterns only"}


def profile_of(tenant: Tenant) -> BusinessProfile:
    return BusinessProfile.model_validate(tenant.profile or {})


@dataclass
class _State:
    """What the business has configured, read once per request."""

    profile: BusinessProfile
    inboxes: list[Mailbox]
    shop: str | None  # the connected Shopify store's domain
    shopify: ShopifySettingsData
    reading: ReadingSettingsData
    payouts: PayoutSettingsData
    connectors: list[str]
    credentials: int
    rules: int

    @property
    def active_inboxes(self) -> list[Mailbox]:
        return [m for m in self.inboxes if m.is_active]

    @property
    def reads_order_numbers(self) -> bool:
        return self.reading.enabled and any(f.key == "orderNumber" for f in self.reading.fields)

    def issues(self, prefix: str) -> bool:
        return self.payouts.enabled and any(
            m.startswith(prefix) for m in self.payouts.methods.values()
        )


class SetupService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tenants = TenantRepository(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def _state(self, tenant: Tenant) -> _State:
        found = shopify_step(self.session, tenant)
        return _State(
            profile=profile_of(tenant),
            inboxes=list(
                self.session.scalars(
                    select(Mailbox).where(Mailbox.tenant_id == tenant.id).order_by(Mailbox.name)
                )
            ),
            shop=found[1].config.get("shop") if found else None,
            shopify=ShopifySettingsData.model_validate(tenant.shopify_settings or {}),
            reading=ReadingSettingsData.model_validate(tenant.reading_settings or {}),
            payouts=PayoutSettingsData.model_validate(tenant.payout_settings or {}),
            connectors=[
                c.name for c in ConnectorRepository(self.session).list(tenant.id, active_only=True)
            ],
            credentials=len(CredentialRepository(self.session).list(tenant.id)),
            rules=len(CompensationRuleRepository(self.session).list(tenant.id, active_only=True)),
        )

    # ----- setup checklist -----------------------------------------------------------------

    def info(self, tenant_id: uuid.UUID, applied: list[str] | None = None) -> SetupInfo:
        state = self._state(self._tenant(tenant_id))
        return SetupInfo(
            profile=state.profile,
            steps=steps_for(state),
            marketplaces=MARKETPLACES,
            applied=applied or [],
        )

    def save(self, tenant_id: uuid.UUID, profile: BusinessProfile) -> SetupInfo:
        tenant = self._tenant(tenant_id)
        tenant.profile = profile.model_dump(mode="json")
        applied: list[str] = []
        reading = ReadingSettingsData.model_validate(tenant.reading_settings or {})
        if profile.sells_on and not reading.enabled and not reading.fields:
            # Order numbers in emails: what makes lookups and rules work on email cases.
            reading.enabled, reading.fields = True, [ORDER_FIELD]
            tenant.reading_settings = reading.model_dump(mode="json")
            applied.append("Reading order numbers out of customers' emails is now on.")
        self.session.commit()
        return self.info(tenant_id, applied)

    # ----- integrations --------------------------------------------------------------------

    def integrations(self, tenant_id: uuid.UUID) -> IntegrationsInfo:
        return IntegrationsInfo(
            cards=cards_for(self._state(self._tenant(tenant_id)), self.settings)
        )


def _marketplace_names(profile: BusinessProfile) -> str:
    return ", ".join(profile.marketplaces) or "your marketplace"


def steps_for(state: _State) -> list[SetupStep]:
    """The next things to do, for where this business sells. Ticked from real settings."""
    profile = state.profile
    sells = set(profile.sells_on)
    steps: list[SetupStep] = []
    if "shopify" in sells:
        steps.append(
            SetupStep(
                key="shopify",
                title="Connect your Shopify store",
                detail="Every case gets its order (total, delivery, tracking, days late), and "
                "refunds, store credit and discount codes can be issued on the store.",
                done=state.shop is not None,
                link="/ops/shopify",
            )
        )
    where = []
    if "shopify" in sells:
        where.append("your Shopify store's customer email (its contact form sends there)")
    if "marketplace" in sells:
        where.append(
            f"the email on your {_marketplace_names(profile)} seller account (buyers who click "
            "Contact land there)"
        )
    if "own_site" in sells:
        where.append("the address your website's contact form sends to")
    steps.append(
        SetupStep(
            key="inbox",
            title="Link your support inbox",
            detail="Every email becomes a case and your replies are sent from it. Use "
            + ("; or ".join(where) if where else "the address customers write to")
            + ".",
            done=bool(state.active_inboxes),
            link="/ops/email" if state.inboxes else "/ops/email/new",
        )
    )
    steps.append(
        SetupStep(
            key="reading",
            title="Read order numbers from emails",
            detail="Emails don't have an order number field: the order number is read out of "
            "the message, so lookups and rules work on email cases.",
            done=state.reads_order_numbers,
            link="/ops/reading",
        )
    )
    steps.append(
        SetupStep(
            key="rules",
            title="Decide what customers get",
            detail="Compensation rules: e.g. a late delivery gets a 15% refund, a damaged item a "
            "$15 code. Approval is asked for repeat claims and big amounts."
            + (
                f" {_marketplace_names(profile)} holds your buyers' payments, so issue those "
                "refunds in your seller dashboard; Local CRM records the decision and drafts the "
                "reply."
                if "marketplace" in sells and "shopify" not in sells
                else ""
            ),
            done=state.rules > 0,
            link="/ops/compensation",
        )
    )
    if "shopify" in sells:
        steps.append(
            SetupStep(
                key="payouts_shopify",
                title="Issue compensation through Shopify",
                detail="Approved refunds, store credit and discount codes go out on your store, "
                "automatically or with one click.",
                done=state.issues("shopify_"),
                link="/ops/payouts",
            )
        )
    if sells & {"own_site", "in_store"}:
        steps.append(
            SetupStep(
                key="payouts_stripe",
                title="Connect Stripe, if you take payments with it",
                detail="Refunds to the original payment, balance credit and voucher codes.",
                done=state.issues("stripe_") and state.payouts.credential_id is not None,
                link="/ops/payouts",
                optional=True,
            )
        )
        steps.append(
            SetupStep(
                key="connectors",
                title="Connect your order system",
                detail="Any system with an API (orders, shipping, loyalty) can add its data to "
                "each case.",
                done=bool(state.connectors),
                link="/ops/connectors/new" if not state.connectors else "/ops/connectors",
                optional=True,
            )
        )
    return steps


def cards_for(state: _State, settings: Settings) -> list[IntegrationCard]:
    sells = set(state.profile.sells_on)
    inboxes = state.active_inboxes
    broken = [m for m in inboxes if m.last_error]
    cards = [
        # ----- store platforms -----
        IntegrationCard(
            key="shopify",
            name="Shopify",
            group="store",
            status="connected" if state.shop else "not_connected",
            summary=(
                f"{state.shop} · order lookup {'on' if state.shopify.enabled else 'off'}"
                if state.shop
                else "Order lookup on every case; refunds, store credit and discount codes "
                "issued on your store."
            ),
            link="/ops/shopify",
            recommended="shopify" in sells,
        ),
        IntegrationCard(
            key="marketplaces",
            name="Marketplaces (SHOP.COM, Amazon, Etsy…)",
            group="store",
            status=(
                "connected"
                if "marketplace" in sells and inboxes and state.reads_order_numbers
                else "not_connected"
            ),
            summary=(
                f"{_marketplace_names(state.profile)}: buyer messages arrive in your seller email "
                "inbox, and order numbers are read from them."
            ),
            link="/ops/email" if inboxes else "/ops/email/new",
            recommended="marketplace" in sells,
        ),
        IntegrationCard(
            key="woocommerce",
            name="WooCommerce, Square, Wix",
            group="store",
            status="coming_soon",
            summary="Built-in order lookup. Until then: a connector to the platform's API.",
            link="/ops/connectors/new",
        ),
        # ----- messages -----
        IntegrationCard(
            key="email",
            name="Email inboxes",
            group="messages",
            status=("needs_attention" if broken else "connected" if inboxes else "not_connected"),
            summary=(
                f"{broken[0].address}: {broken[0].last_error}"
                if broken
                else ", ".join(m.address for m in inboxes)
                if inboxes
                else "Gmail, Outlook.com, iCloud, Yahoo, Zoho or any IMAP inbox: every email "
                "becomes a case."
            ),
            link="/ops/email",
            recommended=True,
        ),
        IntegrationCard(
            key="reading",
            name="Reading messages",
            group="messages",
            status="connected" if state.reading.enabled else "not_connected",
            summary=(
                f"With {READERS.get(reader_kind(settings), 'patterns')}: "
                + (", ".join(f.label for f in state.reading.fields) or "category only")
                if state.reading.enabled
                else "Pull order numbers and other details out of emails; choose the category."
            ),
            link="/ops/reading",
            recommended=bool(sells),
        ),
        IntegrationCard(
            key="webform",
            name="Webform and API",
            group="messages",
            status="connected",
            summary="Always on: cases from a contact form on your site, or any app, via the API.",
            link="/webform",
        ),
        # ----- payments -----
        IntegrationCard(
            key="payouts",
            name="Payouts",
            group="payments",
            status="connected" if state.payouts.enabled else "not_connected",
            summary=(
                ", ".join(
                    f"{kind.replace('_', ' ')} via {method.split('_')[0].title()}"
                    for kind, method in state.payouts.methods.items()
                    if method != "manual"
                )
                or "everything by hand"
                if state.payouts.enabled
                else "Issue approved compensation automatically through Shopify or Stripe."
            ),
            link="/ops/payouts",
            recommended=bool(sells & {"shopify", "own_site"}),
        ),
        IntegrationCard(
            key="stripe",
            name="Stripe",
            group="payments",
            status=(
                "connected"
                if state.payouts.credential_id and state.issues("stripe_")
                else "not_connected"
            ),
            summary="Refunds to the original payment, balance credit and voucher codes.",
            link="/ops/payouts",
            recommended=bool(sells & {"own_site", "in_store"}),
        ),
        IntegrationCard(
            key="cash",
            name="Cash to customers (PayPal, Wise)",
            group="payments",
            status="coming_soon",
            summary="Sending money to a customer's bank or PayPal account.",
        ),
        # ----- your systems -----
        IntegrationCard(
            key="connectors",
            name="Your own systems (connectors)",
            group="systems",
            status="connected" if state.connectors else "not_connected",
            summary=(
                ", ".join(state.connectors)
                if state.connectors
                else "Any API (orders, shipping, loyalty) can add its data to every case."
            ),
            link="/ops/connectors",
            recommended=bool(sells & {"own_site", "in_store"}),
        ),
        IntegrationCard(
            key="credentials",
            name="Credentials",
            group="systems",
            status="connected" if state.credentials else "not_connected",
            summary=(
                f"{state.credentials} saved (encrypted, write-only)"
                if state.credentials
                else "API keys, tokens and OAuth for your connectors."
            ),
            link="/ops/credentials",
        ),
        IntegrationCard(
            key="ai",
            name="AI reply drafts",
            group="systems",
            status="connected" if settings.anthropic_api_key else "not_connected",
            summary=(
                "Claude drafts replies in your voice; you approve every one."
                if settings.anthropic_api_key
                else "Needs an Anthropic API key in the installation's .env file."
            ),
            link="/ops/templates",
        ),
    ]
    return cards
