"""The revision adding the raw response columns to `request_idempotency_keys` (IAN-339).

It is the expand half of an expand/contract change: three nullable columns are added beside the
JSONB `response_body`, which stays, so a row written before the deploy still replays and a
replica still running the old code still reads the column it knows. Each fact is read from
Postgres, and the downgrade is run to show it removes exactly what the upgrade added.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

REVISION_BEFORE_RESPONSE_COLUMNS = "20260924_0007"
RESPONSE_COLUMNS_SQL = text(
    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
    "WHERE table_name = 'request_idempotency_keys' AND column_name LIKE 'response_%' "
    "ORDER BY column_name"
)

AlembicConfigFactory = Callable[[str], Config]


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def read_response_columns(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    """Return every response_* column with its type and nullability, by name."""
    async with engine.connect() as connection:
        rows = (await connection.execute(RESPONSE_COLUMNS_SQL)).all()
    return [(row.column_name, row.data_type, row.is_nullable) for row in rows]


@pytest.mark.integration
async def test_the_raw_response_columns_sit_beside_the_json_body_and_are_nullable(
    database_engine: AsyncEngine,
) -> None:
    """Bytes, content type, and headers are added; the JSONB body is kept for old rows."""
    assert await read_response_columns(database_engine) == [
        ("response_body", "jsonb", "YES"),
        ("response_body_bytes", "bytea", "YES"),
        ("response_content_type", "text", "YES"),
        ("response_headers", "jsonb", "YES"),
    ]


@pytest.mark.integration
async def test_the_response_columns_revision_downgrades_to_the_json_body_alone(
    migrated_database_url: str,
    alembic_config_factory: AlembicConfigFactory,
    database_engine: AsyncEngine,
) -> None:
    """Downgrading one step drops the three columns; the upgrade back to head restores them."""
    config = alembic_config_factory(migrated_database_url)
    try:
        await asyncio.to_thread(command.downgrade, config, REVISION_BEFORE_RESPONSE_COLUMNS)
        assert await read_response_columns(database_engine) == [
            ("response_body", "jsonb", "YES"),
        ]
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
    assert len(await read_response_columns(database_engine)) == 4
