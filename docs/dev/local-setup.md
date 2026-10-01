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
| See API / UI logs | `docker compose logs -f api` / `docker compose logs -f ui` |
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
