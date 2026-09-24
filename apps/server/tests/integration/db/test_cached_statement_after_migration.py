"""Integration tests for what a migration run under traffic does to the API's cached statements.

The asyncpg dialect caches one prepared statement per SQL string on every pooled connection. When
another process changes the type of a column such a statement returns, Postgres refuses the next
execution of it with "cached plan must not change result type" (`InvalidCachedStatementError`),
and because the request's transaction is already aborted, the request answers 500 (IAN-347).

Two behaviors are pinned against the real Postgres and the engine `create_app()` builds:

- An additive change, a new column, leaves every cached statement valid, so a migration that
  follows expand and contract never produces the error. This is the guarantee the README's
  migration rule depends on.
- An in-place type change fails exactly one request, and the next one succeeds without a restart:
  on the error, the dialect bumps a process-wide invalidation timestamp, and every connection then
  re-prepares any statement cached before it. If a SQLAlchemy upgrade removed that recovery, the
  second assertion would fail and the chosen answer (documentation, not a disabled cache) would
  need revisiting.

The schema change runs on an engine of its own, as `alembic upgrade head` would from the
pre-deploy step, because DDL emitted on the application's own engine invalidates its cache first.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.constants.error_codes import ErrorCode

PROBE_PATH = "/test-only/cached-statement/probe"
PROBE_TABLE_NAME = "cached_statement_probe"
PROBE_AMOUNT = 5
STALE_PLAN_ERROR_NAME = "InvalidCachedStatementError"
REQUESTS_AFTER_RECOVERY = 3

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]

DROP_PROBE_TABLE_SQL = text(f"DROP TABLE IF EXISTS {PROBE_TABLE_NAME}")
CREATE_PROBE_TABLE_SQL = text(
    f"CREATE TABLE {PROBE_TABLE_NAME} (id integer PRIMARY KEY, amount integer)"
)
INSERT_PROBE_SQL = text("INSERT INTO cached_statement_probe (id, amount) VALUES (1, :amount)")
SELECT_PROBE_SQL = text("SELECT id, amount FROM cached_statement_probe WHERE id = 1")
ADD_COLUMN_SQL = text(f"ALTER TABLE {PROBE_TABLE_NAME} ADD COLUMN note text")
WIDEN_AMOUNT_SQL = text(f"ALTER TABLE {PROBE_TABLE_NAME} ALTER COLUMN amount TYPE bigint")


def build_probe_router() -> APIRouter:
    """Return one route that reads the probe row through the request's pooled connection."""
    from app.db.session import get_connection  # noqa: PLC0415

    router = APIRouter()
    connection_dependency = Annotated[AsyncConnection, Depends(get_connection, scope="function")]

    @router.get(PROBE_PATH)
    async def read_probe_amount(connection: connection_dependency) -> dict[str, int]:
        """Answer the probe row's amount, through the statement the connection has cached."""
        probe_row = (await connection.execute(SELECT_PROBE_SQL)).one()
        return {"amount": probe_row.amount}

    return router


@pytest_asyncio.fixture
async def migration_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield a second engine standing in for the migration process, with the probe table built."""
    engine = create_async_engine(migrated_database_url)
    async with engine.begin() as connection:
        await connection.execute(DROP_PROBE_TABLE_SQL)
        await connection.execute(CREATE_PROBE_TABLE_SQL)
        await connection.execute(INSERT_PROBE_SQL, {"amount": PROBE_AMOUNT})
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(DROP_PROBE_TABLE_SQL)
        await engine.dispose()


@asynccontextmanager
async def open_probe_client(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client for the built app, after one request has cached the probe statement."""
    application = build_server_app(
        test_only_router=build_probe_router(), database_url=migrated_database_url
    )
    async with build_api_client(application) as client:
        warm_response = await client.get(PROBE_PATH)
        assert warm_response.status_code == 200, warm_response.text
        yield client


async def apply_schema_change(migration_engine: AsyncEngine, change_sql: TextClause) -> None:
    """Run one DDL statement from the migration engine, outside the application's process pool."""
    async with migration_engine.begin() as connection:
        await connection.execute(change_sql)


@pytest.mark.integration
async def test_an_additive_migration_leaves_the_cached_statements_valid(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
    migration_engine: AsyncEngine,
) -> None:
    """A new column changes nothing a cached SELECT returns, so every request still answers 200."""
    async with open_probe_client(
        build_server_app, build_api_client, migrated_database_url
    ) as client:
        await apply_schema_change(migration_engine, ADD_COLUMN_SQL)
        responses = [await client.get(PROBE_PATH) for _ in range(REQUESTS_AFTER_RECOVERY)]

    assert [response.status_code for response in responses] == [200] * REQUESTS_AFTER_RECOVERY
    assert responses[0].json() == {"amount": PROBE_AMOUNT}


@pytest.mark.integration
async def test_an_in_place_type_change_fails_one_request_and_the_next_recovers(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
    migration_engine: AsyncEngine,
) -> None:
    """Widening a column the cached SELECT returns answers one 500, then the app heals itself."""
    async with open_probe_client(
        build_server_app, build_api_client, migrated_database_url
    ) as client:
        await apply_schema_change(migration_engine, WIDEN_AMOUNT_SQL)
        failed_response = await client.get(PROBE_PATH)
        recovered_responses = [await client.get(PROBE_PATH) for _ in range(REQUESTS_AFTER_RECOVERY)]

    assert failed_response.status_code == 500, failed_response.text
    assert failed_response.json()["code"] == ErrorCode.SERVER_INTERNAL_ERROR
    assert STALE_PLAN_ERROR_NAME in failed_response.json()["error"]
    assert [response.status_code for response in recovered_responses] == [
        200
    ] * REQUESTS_AFTER_RECOVERY
    assert recovered_responses[0].json() == {"amount": PROBE_AMOUNT}
