# Database Guide: Postgres for Document-Database Developers

Written for someone who knows DocumentDB/MongoDB and is new to Postgres, SQLAlchemy and Alembic.

## Tables today

| Table | Holds | Notes |
|---|---|---|
| `tenants` | Businesses using the platform, with their settings as JSON (`compensation_settings`, `reading_settings`, `payout_settings`, `shopify_settings`) | Every other table has a `tenant_id` |
| `customers` | People who contact a business | Unique per tenant by email |
| `queues` | Where cases wait: priority, match rules, handling settings (incl. AI model) | Deactivated, never deleted |
| `cases` | The case: status, queue, category, `attributes`, `enrichment`, `decisions` (compensation), `extraction` (what was read from the message), `mailbox_id` (email cases) | Public **case number** (Unix µs); optimistic locking via `version` |
| `messages` | Customer messages, agent replies, internal notes, AI drafts | AI drafts carry `ai` details; email messages carry `external_id` (Message-ID, unique per tenant) and `email` (subject, headers, delivery status) |
| `mailboxes` | Linked email inboxes (IMAP/SMTP) | Password encrypted; IMAP position (`uid_validity`, `last_uid`) and status |
| `case_events` | Audit trail | Append-only |
| `compensation_rules` | The compensation matrix: conditions + outcome per rule | Decisions live on the case in `decisions.compensation`; guardrails in `tenants.compensation_settings` |
| `payouts` | Compensation issued through Stripe: one row per attempt round, with status, Stripe id and error | `idempotency_key` is unique, so one decision can't be paid twice; settings in `tenants.payout_settings` |
| `connectors` | API calls that enrich cases | Request, auth, field mapping, conditions |
| `credentials` | Shared auth for connectors | Secrets encrypted; generated tokens cached |
| `jobs` | Background work (reading, enrichment, email, payouts, template tests) | Picked up with `FOR UPDATE SKIP LOCKED` |
| `prompt_templates` / `prompt_template_versions` | Jinja prompt templates and their immutable versions | One row per name per tenant |
| `sample_cases` | Test-lab inputs | |
| `template_test_runs` | Test-lab runs and results | Results added as each draft finishes |

## 1. Vocabulary map

| Document database | Postgres | In this codebase |
|---|---|---|
| Collection | **Table** | A class in `app/models/` (e.g. `Case` → `cases`) |
| Document | **Row** | An instance of that class |
| Field | **Column** | `mapped_column(...)` on the class |
| Embedded document | **JSONB column** *or* a separate table | `Case.enrichment` (JSONB) vs. `messages` (own table) |
| `_id` | **Primary key** | `id` (UUID) on every table |
| Manual reference (`customerId`) | **Foreign key**: the database *guarantees* it points at a real row | `Case.customer_id → customers.id` |
| Index | Index | `Index(...)` in `__table_args__` |
| Schema-less | Schema **enforced**, changed via **migrations** | `alembic/versions/` |
| Multi-document transaction | Transaction (the default, and cheap) | One `session.commit()` per service method |

## 2. Why some data is columns and some is JSON

**Rule of thumb:** if you **filter, sort, join or enforce** on it, make it a column. If its shape varies (per tenant, per connector) and you mostly read it as a whole, use JSONB.

| Column (strict) | JSONB (flexible) |
|---|---|
| `status`, `queue_id`, `customer_id`, timestamps, `version` | `attributes` (tenant custom fields), `enrichment` (connector output), `decisions`, `flags`, `sla`, `category` |

JSONB is still queryable and indexable when you need it (e.g. `WHERE flags->>'sensitive' = 'true'`), so a field can start in JSON and move to a column later if it becomes important.

## 3. JSON columns: document-style data inside Postgres

JSON columns use `JSONType` (`models/base.py`): JSONB on Postgres, plain JSON in the SQLite test database.

**The one gotcha: nested changes aren't detected.**

```python
case.flags["sensitive"] = True                  # ✅ saved (top-level key)
case.enrichment["order"]["status"] = "ok"       # ❌ NOT saved (nested change)

case.enrichment = {**case.enrichment, "order": {**case.enrichment["order"], "status": "ok"}}  # ✅ saved
```

When in doubt, replace the whole value.

## 4. Changing the schema (migrations)

In a document database you just start writing a new field. In Postgres the table must be changed first. **Alembic** manages that as a series of numbered, reviewable scripts in `alembic/versions/`. Every environment (your laptop, staging, production) runs the same scripts in the same order, so all databases end up identical.

### Workflow for a schema change

```bash
cd backend
# 1. Edit or add the model in app/models/ (and import new models in app/models/__init__.py)

# 2. Generate a migration by comparing models to the database (needs Postgres running)
uv run alembic revision --autogenerate -m "add priority to cases"

# 3. READ the generated file in alembic/versions/. Autogenerate is a draft, not gospel:
#    - renamed columns show up as drop + add (which would delete data): fix them by hand
#    - new NOT NULL columns on existing tables need a default or a backfill step

# 4. Apply it
uv run alembic upgrade head

# 5. Confirm models and migrations agree (no output diff = good)
uv run alembic check
```

### Useful commands

| Command | Does |
|---|---|
| `alembic upgrade head` | Apply all pending migrations |
| `alembic downgrade -1` | Undo the last migration |
| `alembic current` | Show which migration the database is at |
| `alembic history` | List all migrations |
| `alembic upgrade head --sql` | Print the SQL without running it (good for review) |

### Rules

- **Never edit a migration that has run anywhere except your own laptop.** Write a new one instead.
- **Never change production tables by hand.** Everything goes through a migration.
- Migrations target **Postgres only** (they use JSONB). Tests don't run migrations; they build tables from the models on SQLite.

## 5. Transactions

Every service method is one transaction:

```python
case.status = "Queued"             # change 1
self.events.add(CaseEvent(...))    # change 2
self.session.commit()              # both saved together, or neither
```

If anything raises before `commit()`, the session is closed at the end of the request and **everything rolls back**. This is why the case and its audit event can never disagree.

## 6. Optimistic locking (`Case.version`)

Two actors (say an agent and the AI) load the same case at version 3. The first save succeeds and bumps it to version 4. The second save runs `UPDATE ... WHERE id = ? AND version = 3`, matches nothing, and SQLAlchemy raises `StaleDataError`. The service turns that into a **409 Conflict**, so the second actor reloads and decides again instead of silently overwriting.

Clients can also send `expected_version` on transitions to get the same protection across a slow UI interaction.

## 7. Looking at the data

```bash
docker compose exec db psql -U resolve -d resolve
```

```sql
\dt                                   -- list tables
\d cases                              -- describe a table
SELECT id, status, created_at FROM cases ORDER BY created_at DESC LIMIT 10;
SELECT event_type, from_status, to_status, actor_type, reason, occurred_at
  FROM case_events WHERE case_id = '<id>' ORDER BY occurred_at;
SELECT attributes->>'orderNumber' AS order_no FROM cases;   -- read inside JSONB
\q                                    -- quit
```

A GUI client like **TablePlus**, **DBeaver** or **pgAdmin** can connect to `localhost:5432` with user `resolve`, password `resolve`, database `resolve`.

## 8. Testing strategy

| Layer | Database | Why |
|---|---|---|
| `tests/` (pytest) | In-memory SQLite | Fast (~0.1s), no setup. Covers business logic and API behaviour. |
| Migrations + Postgres-specific behaviour | Real Postgres | Run `alembic upgrade head && alembic check` against the Docker database before merging schema changes. |

Later, a CI job should run the test suite against a real Postgres container too.
