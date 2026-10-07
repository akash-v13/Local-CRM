"""Create a demo business with realistic data, through the public API.

    cd backend
    uv run python scripts/seed_demo.py                 # needs `docker compose up` running
    uv run python scripts/seed_demo.py --with-ai       # also writes 2 AI drafts (~$0.02)

Creates "Northwind Outfitters (demo)", a fictional online shop:
- queues: Priority customers, Delivery issues (+ the default General queue)
- 3 credentials + 3 connectors (shop orders → shipping tracker → loyalty program)
  calling the mock API (docker-compose "mocks")
- compensation rules and guardrails
- Stripe payouts (test mode, against the fake Stripe in the mocks service)
- a persona template for the Priority customers queue, and test-lab sample cases
- message reading: order numbers pulled out of incoming emails
- 7 cases in different states: auto-approved compensation, a repeat claim
  waiting for approval, no compensation (weather), a failed shop lookup,
  replies, notes, solved

Also creates "Harbor Goods (Shopify demo)", a small store run by its owner and
connected to the fake Shopify in the mocks service: order lookup by order number or
email, rules on Shopify's data (days late, order email matches), and compensation
issued on the store (a refund, store credit, a discount code), plus a case quoting
someone else's order. `--no-shopify` skips it. And "Seaside Crafts (SHOP.COM seller
demo)", a marketplace seller who has only answered "Where do you sell?".

It talks to the API like any client would, so it also works as a smoke test.
Running it again creates another demo business; nothing is overwritten.
All names, emails and orders are made up.
"""

import argparse
import smtplib
import sys
import time
from email.message import EmailMessage
from typing import Any

import httpx

MOCKS = "http://mocks:8100"  # how the API/worker reach the mock API inside docker-compose
LOCAL_MOCKS = "http://localhost:8100"  # the same mock API, from this machine
SHOP = "harbor-goods.myshopify.com"
MAIL_HOST = "mail"  # the test mail server, as the API/worker reach it inside docker-compose
LOCAL_SMTP = ("localhost", 3025)  # the same server, from this machine
AGENT = "agent.alex"
MANAGER = "manager.sam"


class Api:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=120)

    def call(self, method: str, path: str, body: Any = None, **params: Any) -> Any:
        response = self.http.request(method, path, json=body, params=params or None)
        if response.status_code >= 400:
            sys.exit(f"{method} {path} failed ({response.status_code}): {response.text}")
        return response.json() if response.content else None

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.call("POST", path, body if body is not None else {}, **params)

    def put(self, path: str, body: Any, **params: Any) -> Any:
        return self.call("PUT", path, body, **params)

    def patch(self, path: str, body: Any) -> Any:
        return self.call("PATCH", path, body)

    def get(self, path: str) -> Any:
        return self.call("GET", path)


def cond(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"field": field, "op": op, "value": value}


def seed(api: Api, with_ai: bool) -> None:
    tenant = api.post(
        "/tenants", {"name": f"Northwind Outfitters (demo {int(time.time()) % 10000})"}
    )
    t = f"/tenants/{tenant['id']}"
    print(f"Business: {tenant['name']}")
    # Sells on its own website (setup checklist + integrations suggested for that).
    api.put(f"{t}/setup", {"sells_on": ["own_site"], "completed": True})

    # ----- queues --------------------------------------------------------------------------
    general = next(q for q in api.get(f"{t}/queues") if q["name"] == "General")
    ai_on = {"gen_ai_allowed": True, "ai_model": "claude-sonnet-5", "ai_effort": "low"}
    api.patch(f"{t}/queues/{general['id']}", {"settings": {**general["settings"], **ai_on}})
    api.post(
        f"{t}/queues",
        {
            "name": "Priority customers",
            "description": "Gold and Platinum members get a faster, more personal reply.",
            "priority": 10,
            "match_criteria": {
                "match": "all",
                "conditions": [cond("customer.tier", "one_of", ["Gold", "Platinum"])],
            },
            "settings": {
                **general["settings"],
                **ai_on,
                "approval_threshold": 100,
                "sla_first_response_hours": 8,
            },
        },
    )
    api.post(
        f"{t}/queues",
        {
            "name": "Delivery issues",
            "description": "Late, missing and damaged deliveries.",
            "priority": 20,
            "match_criteria": {
                "match": "all",
                "conditions": [cond("category.category", "equals", "Delivery")],
            },
            "settings": {
                **general["settings"],
                **ai_on,
                "approval_threshold": 50,
                "sla_first_response_hours": 24,
            },
        },
    )
    print("  queues ✓")

    # ----- credentials and connectors (mock shop API) ----------------------------------------
    oauth = api.post(
        f"{t}/credentials",
        {
            "name": "Shop API (OAuth)",
            "kind": "oauth2_client_credentials",
            "config": {"token_url": f"{MOCKS}/oauth/token"},
            "secrets": {"client_id": "demo-client", "client_secret": "demo-secret"},
        },
    )
    key = api.post(
        f"{t}/credentials",
        {
            "name": "Shipping API key",
            "kind": "api_key",
            "config": {"header_name": "X-Api-Key"},
            "secrets": {"key": "demo-key"},
        },
    )
    api.post(
        f"{t}/connectors",
        {
            "key": "shop_orders",
            "name": "Shop orders",
            "description": "Order total, delivery dates and carrier from the shop.",
            "run_order": 10,
            "url_template": f"{MOCKS}/orders/{{{{case.attributes.orderNumber}}}}",
            "credential_id": oauth["id"],
            "field_mappings": [
                {"path": "total.amount", "target": "orderTotal", "label": "Order total"},
                {"path": "daysLate", "target": "daysLate", "label": "Days late"},
                {
                    "path": "promisedDeliveryDate",
                    "target": "promisedDate",
                    "label": "Promised date",
                },
                {"path": "carrier", "target": "carrier", "label": "Carrier"},
                {"path": "trackingNumber", "target": "trackingNumber", "label": "Tracking number"},
            ],
        },
    )
    api.post(
        f"{t}/connectors",
        {
            "key": "shipping",
            "name": "Shipping tracker",
            "description": "Who caused a delay, from the carrier's tracking.",
            "run_order": 20,
            "url_template": f"{MOCKS}/shipments/{{{{enrichment.shop_orders.trackingNumber}}}}",
            "credential_id": key["id"],
            "field_mappings": [
                {"path": "fault", "target": "fault", "label": "Fault"},
                {"path": "delayReason", "target": "delayReason", "label": "Delay reason"},
            ],
        },
    )
    loyalty_token = api.post(
        f"{t}/credentials",
        {
            "name": "Loyalty API token",
            "kind": "bearer",
            "secrets": {"token": "demo-loyalty-token"},
        },
    )
    api.post(
        f"{t}/connectors",
        {
            "key": "loyalty",
            "name": "Loyalty program",
            "description": "Points, order history and past claims for the customer.",
            "run_order": 30,
            "url_template": f"{MOCKS}/loyalty/{{{{case.customer.email}}}}",
            "credential_id": loyalty_token["id"],
            "field_mappings": [
                {"path": "points", "target": "points", "label": "Loyalty points"},
                {
                    "path": "ordersLast12Months",
                    "target": "orders12m",
                    "label": "Orders (12 months)",
                },
                {
                    "path": "compensationClaimsLast12Months",
                    "target": "claims12m",
                    "label": "Claims (12 months)",
                },
            ],
        },
    )
    print("  credentials + connectors ✓")

    # ----- compensation ------------------------------------------------------------------------
    api.put(
        f"{t}/compensation/settings",
        {"repeat_lookback_days": 90, "repeat_max_count": 1, "currency": "USD"},
    )
    late = cond("category.subcategory", "equals", "Late delivery")
    api.post(
        f"{t}/compensation/rules",
        {
            "name": "Weather delays: no compensation",
            "description": "Outside our control; apologise, don't compensate.",
            "priority": 5,
            "match_criteria": {
                "match": "all",
                "conditions": [late, cond("enrichment.shipping.fault", "equals", "weather")],
            },
            "outcome": {"type": "none"},
        },
    )
    api.post(
        f"{t}/compensation/rules",
        {
            "name": "Our fault and very late: 50% refund",
            "priority": 10,
            "match_criteria": {
                "match": "all",
                "conditions": [
                    late,
                    cond("enrichment.shipping.fault", "equals", "merchant"),
                    cond("enrichment.shop_orders.daysLate", "greater_than", "5"),
                ],
            },
            "outcome": {
                "type": "refund",
                "amount_mode": "percent",
                "percent": 50,
                "percent_of": "enrichment.shop_orders.orderTotal",
                "cap": 150,
            },
        },
    )
    api.post(
        f"{t}/compensation/rules",
        {
            "name": "Late 4+ days: 15% store credit",
            "priority": 20,
            "match_criteria": {
                "match": "all",
                "conditions": [late, cond("enrichment.shop_orders.daysLate", "greater_than", "3")],
            },
            "outcome": {
                "type": "store_credit",
                "amount_mode": "percent",
                "percent": 15,
                "percent_of": "enrichment.shop_orders.orderTotal",
                "cap": 60,
            },
        },
    )
    print("  compensation rules ✓")

    # ----- payouts through Stripe (the fake Stripe in the mocks service) -------------------------
    stripe = api.post(
        f"{t}/credentials",
        {"name": "Stripe (test mode)", "kind": "bearer", "secrets": {"token": "sk_test_mock"}},
    )
    api.put(
        f"{t}/payouts/settings",
        {
            "enabled": True,
            "credential_id": stripe["id"],
            "auto_pay": True,
            "metadata_key": "order_id",
            "order_field": "attributes.orderNumber",
        },
    )
    print("  Stripe payouts ✓")

    # ----- prompt templates and samples ---------------------------------------------------------
    api.put(
        f"{t}/prompt-templates/queue/PriorityCustomers.jinja",
        {
            "description": "Priority customers: warm, personal, named sign-off",
            "must_include": ["Warm regards"],
            "source": (
                "You are writing as Jordan, a senior member of "
                "{{ business.name }}'s customer care team.\n\n"
                "Voice: warm and personal, but never gushing. Everyday language.\n"
                "Greeting: {% if customer.first_name %}"
                '"Hi {{ customer.first_name }},"{% else %}"Hello,"{% endif %}.\n'
                'Sign-off: "Warm regards," then "Jordan, {{ business.name }}" on the next line.\n'
                "{% if customer.tier %}They're a {{ customer.tier }} member: "
                "thank them once for their loyalty.{% endif %}\n"
            ),
        },
        actor_id=MANAGER,
    )
    for sample in [
        {
            "name": "Late gift, Gold member",
            "category": {
                "type": "Complaint",
                "category": "Delivery",
                "subcategory": "Late delivery",
            },
            "customer_name": "Maya Chen",
            "customer_tier": "Gold",
            "queue_name": "Priority customers",
            "facts": {"daysLate": 6, "orderTotal": 189.0},
            "message": "The birthday present I ordered arrived six days late. The party was over.",
        },
        {
            "name": "Parcel marked delivered, not received",
            "category": {
                "type": "Complaint",
                "category": "Delivery",
                "subcategory": "Missing package",
            },
            "customer_name": "Tom Okafor",
            "queue_name": "Delivery issues",
            "facts": {"trackingStatus": "Delivered", "deliveredAt": "2026-09-28"},
            "message": (
                "Tracking says delivered on Monday but there's nothing here. I want my money back."
            ),
        },
    ]:
        api.post(f"{t}/sample-cases", sample)
    print("  prompt template + samples ✓")

    # ----- cases -------------------------------------------------------------------------------
    def case(
        name: str,
        email: str,
        tier: str | None,
        sub: str,
        order: str,
        message: str,
        category: str = "Delivery",
        type_: str = "Complaint",
    ) -> int:
        customer: dict[str, Any] = {"email": email, "display_name": name}
        if tier:
            customer["tier"] = tier
        created = api.post(
            f"{t}/cases",
            {
                "channel": "webform",
                "customer": customer,
                "category": {"type": type_, "category": category, "subcategory": sub},
                "message": message,
                "attributes": {"orderNumber": order},
            },
        )
        number: int = created["case_number"]
        return number

    cases = {
        "merchant": case(
            "Maya Chen",
            "maya.chen@example.com",
            "Gold",
            "Late delivery",
            "NW-10208",
            "I ordered a birthday present for my son and it arrived over a week late. "
            "The party was on Saturday. Really disappointed.",
        ),
        "carrier": case(
            "Tom Okafor",
            "tom.okafor@example.com",
            None,
            "Late delivery",
            "NW-10204",
            "My jacket was supposed to arrive last week. Where is it?",
        ),
        "repeat": case(
            "Tom Okafor",
            "tom.okafor@example.com",
            None,
            "Late delivery",
            "NW-10211",
            "Another late order! This is the second time this month.",
        ),
        "weather": case(
            "Lena Fischer",
            "lena.fischer@example.com",
            None,
            "Late delivery",
            "NW-10207",
            "My boots are a week late. Can you tell me what happened?",
        ),
        "question": case(
            "Ravi Patel",
            "ravi.patel@example.com",
            "Platinum",
            "Order status",
            "NW-10202",
            "Hi, can I still change the size on my order? Thanks!",
            category="Order",
            type_="Question",
        ),
        "solved": case(
            "Ana Souza",
            "ana.souza@example.com",
            None,
            "Late delivery",
            "NW-10204",
            "Order arrived late but it's here now, just letting you know.",
        ),
        # The mock shop answers "500" order numbers with a server error, so this case
        # shows a failed step (and the shipping step that needed its data being skipped).
        "shop_error": case(
            "Sam Lee",
            "sam.lee@example.com",
            None,
            "Late delivery",
            "NW-500-77",
            "Where is my order? It's late.",
        ),
    }

    # Enrichment runs on the worker; wait until every case has been routed.
    deadline = time.time() + 60
    while time.time() < deadline:
        statuses = [api.get(f"{t}/cases/{n}")["status"] for n in cases.values()]
        if all(s != "Intake" for s in statuses):
            break
        time.sleep(1)
    else:
        sys.exit("Cases weren't enriched within 60s: is the worker running (docker compose up)?")
    print("  cases enriched, routed and compensated ✓")

    def move(n: int, to: str, reason: str | None = None) -> None:
        api.post(
            f"{t}/cases/{n}/transitions",
            {"to_status": to, "actor_type": "human", "actor_id": AGENT, "reason": reason},
        )

    def message(n: int, kind: str, body: str, then: str | None = None) -> None:
        api.post(
            f"{t}/cases/{n}/messages",
            {"kind": kind, "body": body, "author_id": AGENT, "then_status": then},
        )

    move(cases["carrier"], "AssignedAgent")
    message(
        cases["carrier"],
        "internal_note",
        "Carrier confirms a capacity backlog in the region. Credit applied automatically.",
    )
    move(cases["solved"], "AssignedAgent")
    message(
        cases["solved"],
        "agent_reply",
        "Hi Ana, thanks for letting us know, and sorry it took longer than promised. "
        "Enjoy your order!\n\nBest regards,\nThe Northwind team",
        then="Solved",
    )
    move(cases["question"], "AssignedAgent")
    message(cases["question"], "customer_reply", "Also, is the blue one back in stock?")

    # Read incoming emails: order numbers (so the shop lookup works on email cases).
    presets = {p["id"]: p["pattern"] for p in api.get(f"{t}/reading")["presets"]}
    api.put(
        f"{t}/reading",
        {
            "enabled": True,
            "channels": ["email"],
            "read_category": True,
            "min_confidence": 0.6,
            "fields": [
                {
                    "key": "orderNumber",
                    "label": "Order number",
                    "description": (
                        "the order number of the order the customer is writing about now"
                    ),
                    "pattern": presets["code"],
                }
            ],
        },
    )
    seed_email(api, t, tenant["id"])

    if with_ai:
        for key_ in ("merchant", "weather"):
            api.post(f"{t}/cases/{cases[key_]}/drafts", {"actor_id": AGENT})
        print("  AI drafts ✓")

    print("\nDone. Open http://localhost:5173, pick the business in the top bar, and start with:")
    for label, key_ in [
        ("auto-approved refund (Gold, our fault)", "merchant"),
        ("repeat claim waiting for approval", "repeat"),
        ("weather: no compensation", "weather"),
    ]:
        print(f"  {label}: http://localhost:5173/cases/{cases[key_]}")


def seed_email(api: Api, t: str, tenant_id: str) -> None:
    """Connect an inbox on the local test mail server and email it as two customers.
    Skipped (with a note) if the mail server isn't running."""
    inbox = f"support-{tenant_id[:8]}@northwind.example.com"
    try:
        smtplib.SMTP(*LOCAL_SMTP, timeout=3).quit()
    except OSError:
        print("  email: skipped (start the test mail server: docker compose up -d mail)")
        return
    box = api.post(
        f"{t}/mailboxes",
        {
            "name": "Support inbox",
            "address": inbox,
            "display_name": "Northwind Support",
            "provider": "custom",
            "imap_host": MAIL_HOST,
            "imap_port": 3143,
            "imap_security": "none",
            "smtp_host": MAIL_HOST,
            "smtp_port": 3025,
            "smtp_security": "none",
            "username": inbox,
            "password": "demo-password",
            "poll_interval_seconds": 30,
            "default_category": {
                "type": "Complaint",
                "category": "Delivery",
                "subcategory": "Late delivery",
            },
        },
    )
    emails = [
        (
            "Priya Patel <priya.patel@example.com>",
            "Order NW-10211 is over a week late",
            "Hello,\n\nMy order NW-10211 was due last Thursday and still hasn't arrived. "
            "It was a gift. Can you tell me where it is?\n\nThanks,\nPriya",
        ),
        (
            "Marcus Lee <marcus.lee@example.com>",
            "Where is my parcel?",
            "Hi, tracking for order NW-10207 hasn't moved in five days. What's going on?",
        ),
    ]
    with smtplib.SMTP(*LOCAL_SMTP, timeout=10) as smtp:
        for sender, subject, body in emails:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = sender, inbox, subject
            msg.set_content(body)
            smtp.send_message(msg)
    api.post(f"{t}/mailboxes/{box['id']}/check")
    deadline = time.time() + 60
    while time.time() < deadline:
        if api.get(f"{t}/mailboxes/{box['id']}")["imported_total"] >= len(emails):
            print(f"  email: inbox {inbox} connected, {len(emails)} customer emails imported ✓")
            return
        time.sleep(1)
    print(
        "  email: inbox connected, but emails weren't imported within 60s (is the worker running?)"
    )


def seed_shopify(api: Api) -> None:
    """A small store connected to the fake Shopify (mocks/shopify.py)."""
    tenant = api.post(
        "/tenants", {"name": f"Harbor Goods (Shopify demo {int(time.time()) % 10000})"}
    )
    t = f"/tenants/{tenant['id']}"
    print(f"\nBusiness: {tenant['name']}")
    api.put(f"{t}/setup", {"sells_on": ["shopify", "marketplace"], "marketplaces": ["SHOP.COM"]})
    # Who placed which order (only the fake Shopify needs telling).
    owners = {
        "#1006": "priya.raman@example.com",
        "#1020": "marco.rossi@example.com",
        "#1023": "jin.park@example.com",
        "#1013": "owen.hart@example.com",
    }
    httpx.post(f"{LOCAL_MOCKS}/shopify/{SHOP}/_demo/customers", json=owners, timeout=10)
    check = api.post(
        f"{t}/shopify/connect",
        {"shop": SHOP, "client_id": "demo-shopify-client", "client_secret": "demo-shopify-secret"},
    )
    if not check["ok"]:
        sys.exit(f"Shopify demo: couldn't connect ({check['detail']}). Is SHOPIFY_API_BASE set?")
    print(f"  Shopify: {check['detail']} ✓")

    late = cond("category.subcategory", "equals", "Late delivery")
    theirs = cond("enrichment.shopify.emailMatches", "equals", "true")
    rules = [
        (
            "Late 5+ days: 30% refund",
            [late, theirs, cond("enrichment.shopify.daysLate", "greater_than", "4")],
            {
                "type": "refund",
                "amount_mode": "percent",
                "percent": 30,
                "percent_of": "enrichment.shopify.orderTotal",
                "cap": 100,
            },
        ),
        (
            "Late 2-4 days: $10 store credit",
            [late, theirs, cond("enrichment.shopify.daysLate", "greater_than", "1")],
            {"type": "store_credit", "amount": 10},
        ),
        (
            "Damaged item: $15 discount code",
            [cond("category.subcategory", "equals", "Damaged item"), theirs],
            {"type": "voucher", "amount": 15},
        ),
    ]
    for priority, (name, conditions, outcome) in enumerate(rules, start=1):
        api.post(
            f"{t}/compensation/rules",
            {
                "name": name,
                "priority": priority * 10,
                "match_criteria": {"match": "all", "conditions": conditions},
                "outcome": outcome,
            },
        )
    api.put(
        f"{t}/payouts/settings",
        {
            "enabled": True,
            "auto_pay": True,
            "methods": {
                "refund": "shopify_refund",
                "store_credit": "shopify_credit",
                "voucher": "shopify_discount",
            },
        },
    )
    print("  rules on Shopify data + payouts through Shopify ✓")

    def case(name: str, email: str, sub: str, category: str, order: str | None, text: str) -> int:
        created = api.post(
            f"{t}/cases",
            {
                "channel": "webform",
                "customer": {"email": email, "display_name": name},
                "category": {"type": "Complaint" if order else "Question", "category": category,
                             "subcategory": sub},
                "message": text,
                "attributes": {"orderNumber": order} if order else {},
            },
        )  # fmt: skip
        number: int = created["case_number"]
        return number

    numbers = [
        case("Priya Raman", "priya.raman@example.com", "Late delivery", "Delivery", "#1006",
             "My order #1006 came a week late and missed the birthday it was for."),
        case("Marco Rossi", "marco.rossi@example.com", "Late delivery", "Delivery", "1020",
             "Order 1020 arrived a couple of days later than promised."),
        case("Jin Park", "jin.park@example.com", "Damaged item", "Order", "#1023",
             "The vase in order #1023 arrived chipped. Photos attached."),
        case("Elena Novak", "elena.novak@example.com", "Late delivery", "Delivery", "#1013",
             "Order #1013 is very late, I want a refund."),
        case("Priya Raman", "priya.raman@example.com", "Order status", "Order", None,
             "Hi again, will my next order ship the same way?"),
    ]  # fmt: skip
    deadline = time.time() + 60
    while time.time() < deadline:
        cases = [api.get(f"{t}/cases/{n}") for n in numbers]
        payouts = [(c["decisions"].get("compensation") or {}).get("payout") or {} for c in cases]
        if all(c["status"] != "Intake" for c in cases) and all(
            p.get("status") in (None, "succeeded", "failed") for p in payouts
        ):
            break
        time.sleep(1)
    issued = api.get(f"{t}/payouts")
    print(f"  {len(numbers)} cases looked up in Shopify; {len(issued)} compensations issued ✓")


def seed_marketplace(api: Api) -> None:
    """A SHOP.COM seller who has only said where they sell: shows the setup checklist."""
    tenant = api.post(
        "/tenants", {"name": f"Seaside Crafts (SHOP.COM seller demo {int(time.time()) % 10000})"}
    )
    info = api.put(
        f"/tenants/{tenant['id']}/setup",
        {"sells_on": ["marketplace"], "marketplaces": ["SHOP.COM"]},
    )
    done = sum(s["done"] for s in info["steps"])
    print(f"\nBusiness: {tenant['name']}\n  setup: {done} of {len(info['steps'])} steps done ✓")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="Also write AI drafts (needs ANTHROPIC_API_KEY; costs ~$0.02)",
    )
    parser.add_argument("--no-shopify", action="store_true", help="Skip the Shopify demo store")
    args = parser.parse_args()
    seed(Api(args.api), args.with_ai)
    if not args.no_shopify:
        seed_shopify(Api(args.api))
    seed_marketplace(Api(args.api))


if __name__ == "__main__":
    main()
