"""Alembic environment: connects Alembic to our models and database URL."""

from logging.config import fileConfig
from typing import Any

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import get_settings
from app.models import Base  # importing the package registers every table

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def compare_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """SQLite has one floating-point type (REAL) and reports it as FLOAT, so a Double
    column always looks changed there. Not a real difference: ignore it."""
    if (
        context.dialect.name == "sqlite"
        and isinstance(inspected_type, sa.Float)
        and isinstance(metadata_type, sa.Float)
    ):
        return False
    return None  # default comparison


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_type,
            # SQLite (the desktop app) can't ALTER most things in place: autogenerate then
            # writes batch operations, which rebuild the table there and run as normal
            # ALTERs on Postgres.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
