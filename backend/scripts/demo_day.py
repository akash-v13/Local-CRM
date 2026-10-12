"""A demo business for a technical audience: one store selling on Shopify and SHOP.COM,
with one case per thing worth showing. Run after `docker compose up`:

    cd backend && uv run python scripts/demo_day.py

Creates "Brightwater Home (demo …)" and prints the run sheet (docs/demo/technical-demo.md
explains each scenario and what to click). Uses the fake Shopify and the test mail
server from docker-compose; nothing real is called except the AI reader if a
TYPESAFE_API_KEY / ANTHROPIC_API_KEY is set.
"""

import smtplib
import sys
import time
from email.message import EmailMessage
from typing import Any

import httpx
from seed_demo import LOCAL_MOCKS, LOCAL_SMTP, MAIL_HOST, Api, cond

SHOP = "brightwater-home.myshopify.com"
UI = "http://localhost:5173"


def wait_routed(api: Api, t: str, numbers: list[int], timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(api.get(f"{t}/cases/{n}")["status"] != "Intake" for n in numbers):
            return
        time.sleep(1)
    sys.exit("Cases weren't processed in time: is the worker running (docker compose up)?")


def webform(
    api: Api, t: str, name: str, email: str, sub: str, cat: str, order: str, text: str
) -> int:
    created = api.post(
        f"{t}/cases",
        {
            "channel": "webform",
            "customer": {"email": email, "display_name": name},
            "category": {"type": "Complaint", "category": cat, "subcategory": sub},
            "message": text,
            "attributes": {"orderNumber": order},
        },
    )
    number: int = created["case_number"]
    return number


def main() -> None:
    api = Api("http://localhost:8000")
    tenant = api.post("/tenants", {"name": f"Brightwater Home (demo {int(time.time()) % 10000})"})
    t, tid = f"/tenants/{tenant['id']}", tenant["id"]
    print(f"Business: {tenant['name']}")
    api.put(f"{t}/setup", {"sells_on": ["shopify", "marketplace"], "marketplaces": ["SHOP.COM"]})

    # ----- Shopify (the fake one in the mocks service) ------------------------------------
    owners = {
        "#1006": "priya.raman@example.com",
        "#1008": "priya.raman@example.com",
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
        sys.exit(f"Shopify: {check['detail']}")
    print(f"  Shopify: {check['detail']} ✓")

    # ----- reading, queues, automatic replies ----------------------------------------------
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
                    "pattern": presets["order"],
                }
            ],
        },
    )
    general = next(q for q in api.get(f"{t}/queues") if q["name"] == "General")
    api.patch(
        f"{t}/queues/{general['id']}",
        {"settings": {**general["settings"], "auto_send": True, "auto_send_delay_minutes": 360}},
    )
    api.post(
        f"{t}/queues",
        {
            "name": "SHOP.COM marketplace",
            "priority": 10,
            "match_criteria": {
                "match": "all",
                "conditions": [cond("message", "contains_any", ["SHOP.COM", "shop.com"])],
            },
            "settings": {
                **general["settings"],
                "auto_send": True,
                "auto_send_delay_minutes": 120,
                "auto_send_template": (
                    "Hi {{customer.first_name}},\n\nThanks for letting us know about "
                    "{{case.order}} from our SHOP.COM shop, and I'm sorry it went wrong. "
                    "{{compensation.sentence}} We'll arrange it through SHOP.COM within two "
                    "working days.\n\nBest regards,\n{{business.name}}"
                ),
            },
        },
    )
    print("  reading (order numbers), queues, automatic replies (6 h / 2 h) ✓")

    # ----- compensation rules and payouts ----------------------------------------------------
    api.put(
        f"{t}/compensation/settings",
        {"repeat_lookback_days": 90, "repeat_max_count": 1, "currency": "USD"},
    )
    late = cond("category.subcategory", "equals", "Late delivery")
    theirs = cond("enrichment.shopify.emailMatches", "equals", "true")
    rules: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = [
        (
            "SHOP.COM order: replacement through SHOP.COM",
            [cond("message", "contains_any", ["SHOP.COM", "shop.com"])],
            {"type": "replacement"},
        ),
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
                "replacement": "manual",
            },
        },
    )
    print("  compensation rules (incl. repeat-claim guardrail) + payouts through Shopify ✓")

    # ----- webform cases ---------------------------------------------------------------------
    s1 = webform(
        api,
        t,
        "Priya Raman",
        "priya.raman@example.com",
        "Late delivery",
        "Delivery",
        "#1006",
        "My order #1006 came a week late and missed the birthday it was for.",
    )
    wait_routed(api, t, [s1])  # decided first, so the next case of hers is a repeat claim
    cases = {
        "S1 late 7 days: Shopify refund": s1,
        "S2 damaged: discount code": webform(
            api, t, "Jin Park", "jin.park@example.com", "Damaged item", "Order", "#1023",
            "The vase in order #1023 arrived chipped."),
        "S3 someone else's order": webform(
            api, t, "Elena Novak", "elena.novak@example.com", "Late delivery", "Delivery",
            "#1013", "Order #1013 is very late, I want a refund."),
        "S6 repeat claim: needs approval": webform(
            api, t, "Priya Raman", "priya.raman@example.com", "Late delivery", "Delivery",
            "#1008", "Order #1008 is late as well. Second time this month."),
    }  # fmt: skip

    # ----- emails: a SHOP.COM buyer, and a Shopify contact form ---------------------------
    inbox = f"support-{tid[:8]}@brightwater.example.com"
    try:
        smtplib.SMTP(*LOCAL_SMTP, timeout=3).quit()
    except OSError:
        sys.exit("Start the test mail server first: docker compose up -d mail")
    box = api.post(
        f"{t}/mailboxes",
        {
            "name": "Support inbox",
            "address": inbox,
            "display_name": "Brightwater Home",
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
        {
            "From": "Dana Whitfield <dana.whitfield@example.com>",
            "Subject": "Broken lamp - SHOP.COM order",
            "body": "Hello,\n\nI bought the brass table lamp from your SHOP.COM store, order "
            "104821377. It arrived with the shade cracked. I also have an older order "
            "103990214 that was fine. Can you help with the lamp?\n\nThanks,\nDana",
        },
        {
            "From": "Shopify <mailer@shopify.com>",
            "Reply-To": "Marco Rossi <marco.rossi@example.com>",
            "Subject": "New customer message on October 12, 2026 at 9:14 am",
            "body": "You received a new message from your online store's contact form.\n\n"
            "Name:\nMarco Rossi\n\nEmail:\nmarco.rossi@example.com\n\nOrder number:\n#1020\n\n"
            "Comment:\nHi, order #1020 arrived a couple of days later than promised.",
        },
    ]
    with smtplib.SMTP(*LOCAL_SMTP, timeout=10) as smtp:
        for e in emails:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = e["From"], inbox, e["Subject"]
            if "Reply-To" in e:
                msg["Reply-To"] = e["Reply-To"]
            msg.set_content(e["body"])
            smtp.send_message(msg)
    api.post(f"{t}/mailboxes/{box['id']}/check")
    deadline = time.time() + 90
    while time.time() < deadline and api.get(f"{t}/mailboxes/{box['id']}")["imported_total"] < 2:
        time.sleep(1)
    by_email = {c["customer"]["email"]: c["case_number"] for c in api.get(f"{t}/cases")}
    cases["S4 SHOP.COM email: read + marketplace queue"] = by_email["dana.whitfield@example.com"]
    cases["S5 Shopify contact form: store credit"] = by_email["marco.rossi@example.com"]
    wait_routed(api, t, list(cases.values()))
    time.sleep(3)  # payouts and automatic replies run right after routing

    print("\nRun sheet (docs/demo/technical-demo.md):")
    for label, number in sorted(cases.items()):
        detail = api.get(f"{t}/cases/{number}")
        decision = detail["decisions"].get("compensation") or {}
        reply = detail["decisions"].get("auto_reply") or {}
        result = decision.get("label") or decision.get("status") or "no decision"
        print(f"  {label}\n    {UI}/cases/{number}  · {result} · reply {reply.get('status')}")
    print(f"\n  Pipeline: {UI}/ops/pipeline   Payouts: {UI}/ops/payouts   "
          f"Integrations: {UI}/ops/integrations")  # fmt: skip
    print(f"  Pick '{tenant['name']}' in the top bar first.")


if __name__ == "__main__":
    main()
