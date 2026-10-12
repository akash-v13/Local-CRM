# Technical demo: run sheet

For presenting Local CRM to a technical audience in about 25 minutes. The demo business is **Brightwater Home**: a store selling on **Shopify** and on **SHOP.COM**, with six cases that each show one piece of the system. All of it runs on the laptop: a fake Shopify and a test mail server stand in for the real ones.

## Before the demo (10 minutes)

```bash
docker compose up -d                       # Postgres, API, worker, UI, mocks, mail
cd backend && uv run python scripts/demo_day.py
```

The script prints a link for each case. Then:

1. Open **http://localhost:5173** and pick **Brightwater Home (demo …)** in the top bar.
2. Open in tabs: the S1 case, **Operations → Pipeline → Executions**, **Operations → Payouts**, **Operations → Integrations**, **http://localhost:8000/docs**.
3. Check the **TYPESAFE_API_KEY** is set (`.env`): Jev reads the emails. Without it, reading falls back to Claude, then to patterns only (still works, less impressive in S4).
4. Reset any time: run the script again. It creates a fresh business; old ones stay.

## The story in one line

A complaint comes in from any channel. Code reads it, looks up the order, decides what the customer gets by the owner's rules, pays it out exactly once, and replies after a human-like delay. AI only reads and writes, and never decides money.

## Scenarios

| # | Case | What it shows | Click path |
|---|---|---|---|
| S1 | Priya, Shopify order #1006, 7 days late (webform) | Shopify lookup → rule → **refund through Shopify, exactly once** → automatic reply scheduled for 6 h later | Case page: Enrichment card, Compensation card (Issued · Shopify refund), Automatic reply card. Then **Pipeline → Executions → this case**: click step ①. |
| S2 | Jin, #1023, damaged item | **Discount code** created on the store (single use, only for Jin), quoted in the reply | Compensation card shows the code; the scheduled reply already contains it. |
| S3 | Elena quotes order #1013, which is Owen's | **Fraud check:** `emailMatches = false`, no rule matches, the automatic reply is **held** for a person | Enrichment: `emailMatches false`. Automatic reply: "held: No compensation rule matched this complaint". |
| S4 | Dana emails about a **SHOP.COM** order, mentions two order numbers | **Reading:** Jev picks the order she's writing about (104821377, not the older 103990214) and recategorises to *Damaged item*. Shopify has no such order (shown, not guessed). Routed to the **SHOP.COM marketplace** queue; replacement decided; marketplace-specific reply after 2 h | "Read from the message" card (candidates, confidence). Pipeline execution: ⓪ read → ① Shopify (failed, explained) → routing → compensation. |
| S5 | A **Shopify contact-form email** (sent by `mailer@shopify.com`) | The case belongs to **Marco**, read from the form, not to Shopify's sender. 2 days late → **store credit** on his Shopify account | Case page: customer is Marco; the message has the form's order number. Compensation: Store credit issued. |
| S6 | Priya again, #1008, 5 days late | **Repeat-claim guardrail:** second claim in 90 days → **waiting for approval**; the automatic reply is held until someone decides | Compensation card: "Repeat claim…", Approve / Reject. Approve it live: the refund is issued on Shopify within seconds (Payouts page). The held reply stays held; answer from the reply box (or **Draft with AI**), and point out that a person was kept in the loop. |

## Talking points per area (for technical questions)

**Pipeline and data.** FastAPI + SQLAlchemy 2 + Postgres (SQLite for the desktop app). Each case runs: ⓪ read → ① Shopify order → connectors in run order (each can use earlier steps' data via `{{enrichment.<step>.<field>}}`) → routing (first matching queue) → compensation (first matching rule). Background work is a job queue in the database (`FOR UPDATE SKIP LOCKED`), so a crash never loses work and nothing runs twice.

**Reading (S4).** Code finds candidates with a pattern; the model only **chooses** among them (Jev: about $0.00004 and 0.2 s per message), so it can't invent an order number. Below the confidence threshold an agent confirms. Personal data is masked before any prompt leaves the machine.

**Money (S1, S2, S5, S6).** The rules engine decides; the AI never does. One idempotency key per approved decision. Shopify's mandatory `@idempotent` key on refunds; after an unclear error we first look for our own refund (by its note) before retrying with a new key. Discount codes are unique per store, so a retry finds the code it made. Store credit has no idempotency key, so an unclear outcome is never retried automatically. Tests inject dropped connections, throttling, and "succeeded but answered 500" to prove nothing pays twice.

**Automatic replies (S1, S3, S4, S6).** Drafted on arrival (standard template or AI-written from the business's prompt templates), sent after a delay (6 h here) so it reads like a person and leaves time to step in. Held for: pending approval, failed payout, no matching rule on a complaint, an uncertain order number, the customer writing again. Waits for a payout in flight so it can quote the voucher code.

**Any platform (S4, S5).** Email is the universal intake; Shopify is one optional integration. Setup asks "Where do you sell?" and suggests integrations (Operations → Setup / Integrations).

**Security.** Tenant isolation on every query; secrets encrypted and write-only; SSRF checks on every outbound URL; connectors with API keys in a header or URL parameter, masked in every stored request.

**Architecture next (if asked).** v1 ships as a desktop app (Tauri + SQLite) with a thin AWS relay (Lambda, DynamoDB, SES) for webform intake while the laptop is closed; messages are sealed to the device's key, so the cloud can't read them. About $1–2/month per busy store, plus AI (~$0.005/case). See docs/dev/architecture-v1.md.

## Likely questions

| Question | Answer |
|---|---|
| What if the AI is wrong? | It can only pick from candidates the code found; low confidence goes to a person; money is decided by rules, not the model. |
| What stops double refunds? | Idempotency keys + reconciliation after unclear errors; covered by failure-injection tests. |
| Why delay replies 6 hours? | Customers expect a person; it also leaves the owner time to step in. Configurable 0–48 h per queue. |
| Does it work without Shopify? | Yes: S4 is a SHOP.COM seller working entirely by email. |
| Where does data live? | Today on the business's machine (Docker); v1 desktop app with SQLite; the cloud relay only holds sealed messages briefly. |
| How is it tested? | 328 backend + 68 frontend tests in CI, migrations checked on real Postgres and SQLite, AWS infrastructure synthesized with security checks. |

## If something goes wrong

| Symptom | Fix |
|---|---|
| Cases stuck in "Enriching…" | The worker isn't running: `docker compose up -d worker`. |
| S4/S5 missing | Mail server not up: `docker compose up -d mail`, run the script again. |
| No internet | Everything works except Jev/Claude reading: S4 falls back to patterns (both order numbers become candidates, an agent confirms). |
| A page looks stale | Refresh: the case page polls every few seconds. |
