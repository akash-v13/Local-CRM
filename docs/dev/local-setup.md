# Local Setup

There are three ways to run the project, depending on what you're doing.

| Option | You need | Good for |
|---|---|---|
| **A. Tests only** | `uv`, `npm` | Writing code, running the test suites. No database required. |
| **B. Everything in Docker** | Docker Desktop | Running the full stack (database, API, UI) with one command. **Start here.** |
| **C. Postgres in Docker, API + UI on your machine** | Docker Desktop + `uv` + `npm` | Day-to-day development with your IDE's debugger. |

## Prerequisites

- **uv**: Python project manager. Installs the right Python (3.12) automatically.
  Already installed on this machine. Otherwise: `brew install uv`.
- **Node.js + npm** (for the UI outside Docker). Already installed on this machine.
- **Docker Desktop** (for options B and C): https://www.docker.com/products/docker-desktop/
  If `docker` isn't found in a new terminal, run `export PATH="$PATH:$HOME/.docker/bin"`
  or enable the system-wide CLI in Docker Desktop → Settings → Advanced.

## A. Tests only

```bash
cd backend
uv sync          # first time: creates .venv and installs everything
uv run pytest    # ~0.2s, uses an in-memory SQLite database

cd ../frontend
npm install      # first time
npm test         # ~1s, components tested in a simulated browser
```

## B. Everything in Docker

From the repository root:

```bash
docker compose up --build
```

This will:
1. Start Postgres 17 (data is kept in a Docker volume between restarts).
2. Build the API image, run database migrations (`alembic upgrade head`), and start the API with auto-reload.
3. Start the UI (installs npm packages inside the container the first time, then runs the Vite dev server).

Now open:

| URL | What |
|---|---|
| **http://localhost:5173** | The app: agent console + test webform |
| http://localhost:8000/docs | Interactive API docs |

Your code is mounted into the containers: saving a backend file restarts the API, and saving a frontend file updates the browser instantly.

| Task | Command |
|---|---|
| Stop | `Ctrl+C`, or `docker compose down` |
| Stop **and delete all data** | `docker compose down -v` |
| See API / UI / worker logs | `docker compose logs -f api` (or `ui`, `worker`, `mocks`) |
| Open a SQL shell | `docker compose exec db psql -U resolve -d resolve` |
| After changing backend dependencies | `docker compose up --build` |
| After changing frontend dependencies | `docker compose restart ui` (reruns `npm ci`) |

## C. Postgres in Docker, API + UI on your machine

```bash
docker compose up -d db                      # only the database, in the background

# terminal 1: API
cd backend
cp .env.example .env                         # points the API at localhost:5432
uv run alembic upgrade head                  # create/update tables
uv run uvicorn app.main:app --reload         # http://localhost:8000/docs

# terminal 2: UI
cd frontend
npm install
npm run dev                                  # http://localhost:5173
```

## Turn on AI drafting (Anthropic API key)

Everything except AI drafting works without a key. To turn AI drafting on:

1. **Get a key.** Sign in at https://console.anthropic.com, add credit under **Billing**, then create a key under **Settings → API keys**. It starts with `sk-ant-`. Copy it now, because it's only shown once.
2. **Put it in `.env`** in the project root (next to `docker-compose.yml`):

   ```bash
   cp .env.example .env
   # then edit .env so it reads:
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   `.env` is git-ignored. **Never** put the key in code, `docker-compose.yml`, a committed file, or a chat or ticket.
3. **Restart the API and worker** so they read the key:

   ```bash
   docker compose up -d
   ```

4. **Check it worked:**

   ```bash
   docker compose logs worker | grep "AI drafting"
   # → worker started (AI drafting on)
   ```

   In the app, **✨ Draft with AI** on a case now writes a draft. That only happens if the case's queue has **Allow AI to draft replies** ticked (Operations → Queues & routing).

**Reading messages with Jev (optional):** add `TYPESAFE_API_KEY=…` (from https://console.typesafe.ai/settings/keys) to the same `.env` and restart. Without it, Claude reads messages.

**Running the backend outside Docker (option C)?** Put the same `ANTHROPIC_API_KEY=` line in `backend/.env` instead (copy `backend/.env.example`).

**Cost:** a typical draft costs under one cent (see [costs in the main README](../../README.md#ai-costs)). To limit spending, set a monthly limit for the key in the Anthropic Console.

**If it doesn't work:**

| Symptom | Fix |
|---|---|
| "AI drafting isn't set up: add ANTHROPIC_API_KEY…" | The key isn't loaded. Check `.env` is in the project root, then run `docker compose up -d` again. |
| "The Anthropic API key was rejected" | Typo or revoked key: create a new one. |
| "The Anthropic API rejected the request: … credit balance …" | Add credit under **Billing** in the Console. |
| "Rate limited by the Anthropic API" | Wait a minute; new accounts have low limits that rise with usage. |
| "AI drafting is turned off for the 'X' queue" | Tick **Allow AI to draft replies** on that queue. |

## Load demo data

With the stack running, create a made-up shop ("Northwind Outfitters") with queues, connectors to the mock API, compensation rules, Stripe payouts (against the fake Stripe), a second business on a fake Shopify store, a persona template, sample cases and cases in different states:

```bash
cd backend
uv run python scripts/seed_demo.py              # free
uv run python scripts/seed_demo.py --with-ai    # + 2 AI drafts (~$0.02, needs ANTHROPIC_API_KEY)
```

Pick the new business in the top bar. The [Business handbook](../handbooks/business-handbook.md) uses this data in every screenshot.

## Try it in the UI

1. Open http://localhost:5173. If there's no tenant yet, type a business name in the top bar and click **Create**.
2. Go to **Test webform**, fill it in, pick a category and **Submit**.
3. Click **Open in agent console**. The case starts in **Intake**.
4. In the **Status** card: **Move to queue**, then **Assign to me**.
5. In the reply box:
   - **Internal note**: saved, visible to agents only (yellow).
   - **Reply to customer** → **Send & mark solved**: saved as sent (simulated, no email yet) and the case becomes **Solved**.
   - **Simulate customer reply**: pretends the customer wrote back, which reopens the case to **Queued**.
6. The **History** card shows every step with who did it.

### Try the Operations Portal

1. Go to **Operations → Queues & routing**. Every business starts with a catch-all **General** queue.
2. **New queue**: e.g. name "Delivery issues", priority 10, condition *Category is "Delivery"*. Create it.
3. Submit a Delivery complaint through the test webform. It lands in **Delivery issues**; anything else lands in **General**. The case's History shows *why* ("✓ Category is Delivery").
4. On a case, use **Queue → Move to queue…** to reroute manually. The case is then *pinned* there.
5. Open a queue, change its conditions **without saving**, pick a case under **Test with a real case** and **Run test**. You'll see which queue it would land in and why each queue did or didn't match.
6. **Operations → Dashboard** shows open cases, where they're waiting, and a queue × status table. Click any number to open exactly those cases.

### Try enrichment (connectors) with the mock shop API

docker-compose runs a fake shop/shipping API at `http://mocks:8100` (docs: http://localhost:8100/docs).

1. **Operations → Credentials → New credential**:
   - "Shop OAuth": type **OAuth 2.0**, token URL `http://mocks:8100/oauth/token`, client ID `demo-client`, client secret `demo-secret`. Create, then **Generate token now**.
   - "Shipping key": type **API key**, header `X-Api-Key`, key `demo-key`.
2. Submit a test webform case with order number `ORD-55012` (so there's a case to test with).
3. **Operations → Connectors → New connector** "Shop orders": URL `http://mocks:8100/orders/` then **Insert field… → Order number**; authentication "Shop OAuth"; **Send test request**; click **Keep** on `total.amount`, `daysLate`, `trackingNumber`; create.
4. Submit another webform case. It shows "Enriching…" and a moment later the **Enrichment** card fills in.
5. A second connector "Shipping" (run order after the first): URL `http://mocks:8100/shipments/` + **Insert field… → Shop orders: trackingNumber**, credential "Shipping key", keep `fault`.
6. A queue rule like *Shop orders: totalAmount is greater than 500* now routes on enriched data.

Failure testing: order numbers containing `404`, `500` or `SLOW` make the mock API fail or time out.

### Try the compensation matrix

1. **Operations → Compensation → New rule**: e.g. *Late delivery: 25% refund*, condition *Category is Delivery*, **Refund**, **Percentage of a case value**: 25% of the case attribute `orderTotal`, cap 50.
2. Pick a case in **Test with a real case** to see what it would get and why, and run the **backtest** to see what the rule would have cost on recent cases. Then **Create rule**.
3. Submit the test webform (or `POST /cases` with `"attributes": {"orderTotal": 120}`). When the case is routed, the matrix decides: the case page's **Compensation** card shows *Refund of USD 30.00 · Approved*.
4. Submit a second case with the same email: it's a **repeat claim**, so it waits for approval. Approve or reject it on the case page.
5. With AI drafting on, a draft for the first case mentions the refund; the second case's draft won't until it's approved.

### Try the email channel

The stack includes **GreenMail**, a throwaway mail server (SMTP on `localhost:3025`, IMAP on `localhost:3143`; any address works and any password is accepted).

1. **Operations → Email → Connect inbox**: enter an address such as `support@northwind.example.com`, click **Use the local test mail server (development)**, then **Test connection** and **Connect inbox**.
2. Email that address as a customer:

   ```bash
   python3 - <<'PY'
   import smtplib
   from email.message import EmailMessage
   m = EmailMessage()
   m["From"], m["To"], m["Subject"] = "Tom <tom@example.com>", "support@northwind.example.com", "Jacket still not here"
   m.set_content("Hi, my order NW-10204 is 5 days late. Any news?")
   with smtplib.SMTP("localhost", 3025) as s: s.send_message(m)
   PY
   ```
3. Click **Check now** (or wait for the next check). The email becomes a case with its subject.
4. Reply on the case. The message shows **✓ Emailed to tom@example.com**, and the email is in Tom's mailbox on GreenMail (IMAP, username `tom@example.com`, any password).
5. Answer that email from Tom's side (keep the `In-Reply-To` header). It lands on the same case.

The demo seed script does steps 1–3 for you when GreenMail is running.

### Try reading messages

1. **Operations → Reading**: tick **Read new cases' messages**, add an *Order number* field ("Letters then digits"), and use **Test it** on the sample email. It picks NW-10211 over the older NW-10187 mentioned in the same email.
2. Save, then send an email (see above) mentioning an order such as `NW-10208`. The case gets `orderNumber`, the shop lookup runs on it, and **Pipeline → Executions** shows step ⓪.
3. The reader is Jev when `TYPESAFE_API_KEY` is in `.env`, Claude when only `ANTHROPIC_API_KEY` is, and patterns alone otherwise. The worker's start-up log says which.

### Try payouts (Stripe)

docker-compose points payouts at a **fake Stripe** in the mocks service (`STRIPE_API_BASE=http://mocks:8100/stripe`, key `sk_test_mock`). Every order number has a payment (`pi_mock_<order>`, `metadata.order_id=<order>`), every email has a customer, and order numbers containing `404` have no payment. Nothing leaves your machine.

1. **Operations → Credentials → New credential**: type **Bearer token**, name "Stripe (test mode)", token `sk_test_mock`.
2. **Operations → Payouts**: tick **Issue compensation through Stripe**, choose the credential, **Check Stripe** (→ *Connected to Stripe in test mode*), **Save**.
3. Submit a case that a compensation rule approves (see above), with an order number. A moment later the case's **Compensation** card shows **Issued · Stripe refund · re_mock_…**, and **Recent payouts** lists it.
4. Use an order number with `404` in it: the payout **fails** with *Couldn't find the Stripe payment…*; fix it, then **Try again**.

The demo seed script does steps 1–2. To use **real Stripe in test mode**: remove the `STRIPE_API_BASE` line from `docker-compose.yml`, `docker compose up -d`, and put your `sk_test_…` key in the credential instead (never in `.env` or code). Test-mode refunds need a test payment whose metadata has the order number, e.g. `stripe payment_intents create --amount 5000 --currency usd --confirm --payment-method pm_card_visa -d "metadata[order_id]=NW-10211" -d "automatic_payment_methods[enabled]=true" -d "automatic_payment_methods[allow_redirects]=never"` with the Stripe CLI.

### Try Shopify

docker-compose points Shopify at a **fake Shopify** in the mocks service (`SHOPIFY_API_BASE=http://mocks:8100/shopify`). Any `….myshopify.com` domain works; the app's client ID is `demo-shopify-client` and its secret `demo-shopify-secret`. Order numbers like `#1006` exist (with made-up totals, delivery dates and days late); numbers containing `404` don't. Nothing leaves your machine.

1. **Operations → Shopify:** domain `harbor-goods`, client ID and secret as above, **Connect** (→ *Connected to Harbor Goods*).
2. **Test the lookup** with order number `#1006` and email `priya.raman@example.com`: the order is found and *Order email matches* is **Yes**. Try `#1013` with the same email: **No** (it's someone else's order).
3. Submit a webform case with order number `1006` and that email. Its **Enrichment** card shows the Shopify order, and **Pipeline → Executions** shows step ①.
4. Add a compensation rule on *Shopify: Days late*, set **Payouts** to the Shopify methods, and submit another case: the refund, store credit or discount code is issued on the fake store.

The demo seed script creates all of this as *Harbor Goods (Shopify demo)*. To try a **real store**: remove the `SHOPIFY_API_BASE` line from `docker-compose.yml`, `docker compose up -d`, create a free development store in a Shopify Partner account, create an app in the Dev Dashboard with the scopes listed on the Shopify page, install it on the store, and connect with its client ID and secret (in the UI only: never in `.env`, code or chat).

### Try AI reply drafting

First add your Anthropic API key: see [Turn on AI drafting](#turn-on-ai-drafting-anthropic-api-key) above. Then:

1. **Operations → Queues & routing → General** (or any queue): tick **Allow AI to draft replies**, pick the model and effort, save.
2. **Operations → Prompt templates**: every business starts with a starter pack: a baseline (`base.jinja`), a default persona and case-type templates. Edit the baseline for your tone, add a persona for a queue (`queue/General.jinja`) or a template for a category (`category/Complaint_Delivery_LateDelivery.jinja`); **New template** picks the right name for you and starts from the template it replaces.
3. In the editor, click variables to insert them and use **Preview** on a sample or real case to see the exact prompt, layer by layer (free: no model call). Download/upload `.jinja` files to edit them in your own editor.
4. **Operations → Sample cases**: add a few realistic messages with facts (e.g. `daysLate = 6`).
5. In the template's **Test lab**: choose models (e.g. Haiku and Sonnet), samples, 2-3 runs each. The cost estimate shows before you run. **Run test** compares models on checks passed, consistency, length, speed and cost per reply, with replies side by side.
6. **Cost projection** shows per-reply and monthly cost for each model at your volume, measured from your tests.
7. On a case: **✨ Draft with AI** fills the reply box with a draft (plus the templates and versions used, cost, warnings and checks). Edit and send; whether you edited it is recorded.

## Try it with the API directly

In the interactive docs (http://localhost:8000/docs), or with curl:

```bash
# 1. Create a tenant (a business using the platform)
curl -s -X POST localhost:8000/tenants -H 'content-type: application/json' \
  -d '{"name": "Acme Store"}'
# → copy the "id" from the response into TENANT below

TENANT=<paste-id>

# 2. Intake a case
curl -s -X POST localhost:8000/tenants/$TENANT/cases -H 'content-type: application/json' -d '{
  "channel": "webform",
  "customer": {"email": "john.doe@example.com", "display_name": "John Doe", "tier": "Gold"},
  "category": {"type": "Complaint", "category": "Delivery", "subcategory": "Late delivery"},
  "message": "My order arrived almost a week late.",
  "attributes": {"orderNumber": "ORD-55012"}
}'
# → copy the case "id" into CASE below

CASE=<paste-id>

# 3. Move it through the lifecycle
curl -s -X POST localhost:8000/tenants/$TENANT/cases/$CASE/transitions \
  -H 'content-type: application/json' \
  -d '{"to_status": "Queued", "actor_type": "system", "reason": "enrichment complete"}'

# 4. See the audit trail
curl -s localhost:8000/tenants/$TENANT/cases/$CASE/events
```

An invalid move (e.g. `Intake` → `Solved`) returns **409** with a message listing the allowed next statuses.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused` on port 5432 | Postgres isn't running: `docker compose up -d db` |
| `port 5432 already in use` | Another Postgres is running locally. Stop it, or change the left side of `"5432:5432"` in `docker-compose.yml` (and your `.env`). |
| `relation "cases" does not exist` | Migrations not applied: `uv run alembic upgrade head` |
| Import errors when running tools | Run commands from inside `backend/`, and prefix them with `uv run`. |
| UI shows "API unreachable" | The API isn't running, or (outside Docker) isn't on port 8000. Check `docker compose logs api`. |
| UI shows a tenant that no longer exists | After `docker compose down -v` the database is empty. The UI resets automatically on reload; create a new tenant. |
| `port 5173 already in use` | Another Vite server is running (e.g. `npm run dev` in another terminal). Stop it. |
