"""Create a demo business with realistic data, through the public API.

    cd backend
    uv run python scripts/seed_demo.py                 # needs `docker compose up` running
    uv run python scripts/seed_demo.py --with-ai       # also writes 2 AI drafts (~$0.02)

Creates "Northwind Outfitters (demo)", a fictional online shop:
- queues: Priority customers, Delivery issues (+ the default General queue)
- credentials + connectors to the mock shop/shipping API (docker-compose "mocks")
- compensation rules and guardrails
- a persona template for the Priority customers queue, and test-lab sample cases
- 7 cases in different states: auto-approved compensation, a repeat claim
  waiting for approval, no compensation (weather), replies, notes, solved

It talks to the API like any client would, so it also works as a smoke test.
Running it again creates another demo business; nothing is overwritten.
All names, emails and orders are made up.
"""

import argparse
import sys
import time
from typing import Any

import httpx

MOCKS = "http://mocks:8100"  # how the API/worker reach the mock API inside docker-compose
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="Also write AI drafts (needs ANTHROPIC_API_KEY; costs ~$0.02)",
    )
    args = parser.parse_args()
    seed(Api(args.api), args.with_ai)


if __name__ == "__main__":
    main()
