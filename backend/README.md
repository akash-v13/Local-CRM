# Backend

FastAPI + SQLAlchemy + Postgres. Python 3.12, managed with [uv](https://docs.astral.sh/uv/).

## Everyday commands

Run from this `backend/` folder.

| Task | Command |
|---|---|
| Install / update dependencies | `uv sync` |
| Run tests (no database needed) | `uv run pytest` |
| Type check | `uv run mypy app tests` |
| Lint | `uv run ruff check .` |
| Auto-format | `uv run ruff format .` |
| Run the API (needs Postgres) | `uv run uvicorn app.main:app --reload` |
| Run the background worker | `uv run python -m app.worker` |
| Run the mock shop API | `uv run uvicorn mocks.shop:app --port 8100` |
| Apply database migrations | `uv run alembic upgrade head` |
| Create a new migration | `uv run alembic revision --autogenerate -m "describe change"` |
| Check models match migrations | `uv run alembic check` |

Before every commit, run: `uv run pytest && uv run mypy app tests && uv run ruff check .`

## Where things are

```
app/
├── main.py           App entry point; maps domain errors to HTTP status codes
├── config.py         Settings from environment variables
├── db.py             Database engine + session per request
├── api/              HTTP routes (thin: validate → call service → return)
├── schemas.py        API request/response shapes (the public contract)
├── services/         Business operations; one method = one transaction
│   ├── cases.py      Intake, routing, status changes, messages
│   ├── queues.py     Queue management, routing preview, rule-builder fields
│   ├── reports.py    Queue × status report
│   ├── tenants.py    Tenants (+ default "General" queue)
│   ├── connectors.py Connector management + live test
│   ├── credentials.py Credential management + token test
│   ├── enrichment.py Runs connectors for a case (called by the worker), then routes
│   ├── replies.py    Prompt templates (save, preview, coverage, costs) + AI drafts on cases
│   ├── template_tests.py Sample cases + test lab runs (executed by the worker)
│   └── routing.py    Adapts models to the pure routing logic
├── connectors/       Calling external APIs: runner (one request), auth (credentials,
│                     token cache), context (what templates can see)
├── security/         SSRF protection, secret encryption
├── ai/               Reply drafting
│   ├── engine.py     Layered Jinja templates: names, fallbacks, validation, sandboxed rendering
│   ├── context.py    Case → the masked variables templates can use
│   ├── templates/    Locked platform layers + the starter pack (see its README.md)
│   ├── pii.py        Mask / restore personal data
│   ├── drafter.py    The Claude call (structured output, cached system prompt)
│   ├── models.py     Models and prices (every cost comes from here)
│   └── checks.py     Word limits, must / must-not phrases, consistency
├── worker.py         Background worker: `uv run python -m app.worker`
├── repositories.py   The ONLY code that queries the database
├── domain/           Pure business rules — no DB, no HTTP
│   ├── lifecycle.py  Statuses and allowed transitions
│   ├── routing.py    Queue matching (decision list + specifications)
│   ├── taxonomy.py   Case categories for the webform
│   ├── templates.py  {{placeholder}} rendering with safe escaping
│   ├── jsonpath.py   Read values from JSON by dotted path
│   ├── ids.py        Case numbers (Unix microseconds)
│   └── errors.py     Domain errors → HTTP codes (mapped in main.py)
└── models/           Database tables
mocks/shop.py         Fake shop/shipping API for demos (docker-compose "mocks")
alembic/versions/     Migrations (schema history)
tests/                Pytest suite (runs on in-memory SQLite)
```

How a request moves through these layers, and how to add a feature: [../docs/dev/codebase-guide.md](../docs/dev/codebase-guide.md).
