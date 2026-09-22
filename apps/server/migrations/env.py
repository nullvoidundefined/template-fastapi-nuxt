"""Alembic environment: runs the revision chain through the application's own async engine.

`target_metadata` is the metadata in `app/db/tables.py`, so autogenerate compares a draft against
the same table definitions the repositories select from rather than against a second description
of the schema that would drift from it.

The database URL comes from the application's Settings unless a caller set `sqlalchemy.url` in
memory first. That keeps the secret out of `alembic.ini` (R-102) while still letting the
integration fixture and a one-off run point the same chain at another database.
"""

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.settings import get_settings
from app.db.tables import metadata

config = context.config
target_metadata = metadata


def resolve_database_url() -> str:
    """Return the URL the caller configured, falling back to the application's own setting."""
    configured_url = config.get_main_option("sqlalchemy.url", "")
    if configured_url:
        return configured_url
    return get_settings().database_url.get_secret_value()


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
    """Open an async engine, run the chain on a connection borrowed from it, and dispose it.

    `NullPool` is used because the process exits as soon as the chain finishes; a pooled engine
    would hold idle connections open for a lifetime that does not exist here.
    """
    engine = create_async_engine(resolve_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations_on_connection)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
