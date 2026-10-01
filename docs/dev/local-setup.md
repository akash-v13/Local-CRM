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

### Try AI reply drafting

AI drafting calls the Anthropic API, so it needs a key (from https://console.anthropic.com). It costs real money, but little: a typical draft costs well under one cent on Haiku or Sonnet.

Put the key in a `.env` file in the project root (next to `docker-compose.yml`). Docker Compose reads it automatically, and it's git-ignored:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
docker compose up -d                     # recreates api + worker with the key
docker compose logs worker | grep "AI drafting on"
```

Running the backend outside Docker? Put the same line in `backend/.env` instead. Never put the key in code, `docker-compose.yml`, or anything committed.

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
