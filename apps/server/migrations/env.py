"""Alembic environment: runs the revision chain through the application's own async engine.

`target_metadata` is the metadata in `app/db/tables.py`, so autogenerate compares a draft against
the same table definitions the repositories select from rather than against a second description
of the schema that would drift from it.

The database URL comes from the application's Settings unless a caller set `sqlalchemy.url` in
memory first. That keeps the secret out of `alembic.ini` (R-102) while still letting the
integration fixture and a one-off run point the same chain at another database.
"""

import asyncio
import logging
import sys

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.settings import get_settings
from app.db.engine import build_connect_args
from app.db.tables import metadata

config = context.config
target_metadata = metadata

MIGRATION_LOGGER_NAME = "alembic"


def configure_migration_logging() -> None:
    """Make sure Alembic's own INFO lines reach stdout, so a deployed migration is not silent.

    `alembic.ini` deliberately carries no logging configuration and `env.py` never calls
    `fileConfig`, so without this the only handler is Python's last resort, which prints warnings
    and above; `Running upgrade ... ` would never appear in a deploy log. `force=False` leaves an
    already configured root handler alone, so inside a process that ran `configure_logging` the
    lines go through structlog's renderer and come out as JSON like every other line.
    """
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logging.getLogger(MIGRATION_LOGGER_NAME).setLevel(logging.INFO)


def resolve_database_url() -> str:
    """Return the URL the caller configured, falling back to the application's own setting."""
    configured_url = config.get_main_option("sqlalchemy.url", "")
    if configured_url:
        return configured_url
    return get_settings().database_url.get_secret_value()


def build_migration_engine() -> AsyncEngine:
    """Build the engine the chain runs on, with the connect arguments the caller's case needs.

    On the deployed path nothing configured `sqlalchemy.url`, so the engine is built from the same
    Settings the service uses and through the same `build_connect_args`: in staging and production
    that carries the verified TLS context, so a migration cannot be the one connection in the
    system that accepts an unverified certificate or falls back to plaintext. A caller that did
    configure the URL (the integration fixture, a one-off against a branch) owns that decision
    itself and may have no Settings to build at all, so its URL is used as given.

    `NullPool` in both cases, because the process exits as soon as the chain finishes and a pooled
    engine would hold idle connections open for a lifetime that does not exist here.
    """
    configured_url = config.get_main_option("sqlalchemy.url", "")
    if configured_url:
        return create_async_engine(configured_url, poolclass=pool.NullPool)
    settings = get_settings()
    return create_async_engine(
        settings.database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args=build_connect_args(settings),
    )


def run_migrations_offline() -> None:
    """Emit the chain as SQL against a URL, without connecting to anything."""
    context.configure(
        url=resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_on_connection(connection: Connection) -> None:
    """Run the chain on one synchronous connection, inside one transaction."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open the migration engine, run the chain on a connection from it, and dispose it."""
    engine = build_migration_engine()
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations_on_connection)
    finally:
        await engine.dispose()


configure_migration_logging()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
