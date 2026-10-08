"""Migrations on SQLite, the desktop app's database (docs/dev/architecture-v1.md).

CI runs the same round trip on real Postgres (.github/workflows/ci.yml). Here:
upgrade from empty, models match the migrations (no drift), downgrade to empty and
back, and an upgrade over existing data (the case-number backfill).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    url = f"sqlite:///{tmp_path / 'local-crm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()  # alembic/env.py reads the URL from the settings
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["url"] = url
    yield config
    get_settings.cache_clear()


def test_round_trip_on_sqlite(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)  # raises if the models and migrations differ
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(alembic_config.attributes["url"])
    tables = set(sa.inspect(engine).get_table_names())
    assert {"tenants", "cases", "jobs", "payouts", "mailboxes"} <= tables


def test_upgrade_over_existing_data(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "0002")
    engine = sa.create_engine(alembic_config.attributes["url"])
    tenant, customer = uuid.uuid4().hex, uuid.uuid4().hex
    created = [datetime(2026, 9, 1, 12, 0, tzinfo=UTC).isoformat()] * 2  # same instant
    with engine.begin() as db:
        db.execute(
            sa.text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 'Shop', :at)"),
            {"id": tenant, "at": created[0]},
        )
        db.execute(
            sa.text(
                "INSERT INTO customers (id, tenant_id, email, identity_links, created_at) "
                "VALUES (:id, :t, 'a@example.com', '{}', :at)"
            ),
            {"id": customer, "t": tenant, "at": created[0]},
        )
        for at in created:
            db.execute(
                sa.text(
                    "INSERT INTO cases (id, tenant_id, customer_id, status, channel, language, "
                    "category, attributes, flags, sla, enrichment, decisions, assignment_pinned, "
                    "version, created_at, updated_at, status_changed_at) "
                    "VALUES (:id, :t, :c, 'Intake', "
                    "'webform', 'en', '{}', '{}', '{}', '{}', '{}', '{}', 0, 1, :at, :at, :at)"
                ),
                {"id": uuid.uuid4().hex, "t": tenant, "c": customer, "at": at},
            )

    command.upgrade(alembic_config, "head")
    with engine.connect() as db:
        numbers = db.execute(sa.text("SELECT case_number FROM cases ORDER BY case_number")).all()
        defaults = db.execute(sa.text("SELECT reading_settings, profile FROM tenants")).one()
    first, second = (n for (n,) in numbers)
    assert second == first + 1  # unique, in creation order
    assert defaults == ("{}", "{}")  # JSON server defaults filled the new columns
