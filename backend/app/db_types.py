"""Column types and defaults that work on both databases we run on.

- Postgres: the server and Docker setups (and a future hosted tier).
- SQLite: the desktop app, one file on the owner's machine (docs/dev/architecture-v1.md).

Migrations import these instead of Postgres-only types, so the same revision
creates JSONB columns on Postgres and JSON (text) columns on SQLite. The models
use the matching `JSONType` in app/models/base.py.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# A JSON document column: JSONB on Postgres, JSON on SQLite.
JSON_DOC = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

# Server default "{}" for a JSON column. Postgres casts the literal to jsonb itself, so
# no "::jsonb" (which SQLite can't parse).
EMPTY_JSON = sa.text("'{}'")
