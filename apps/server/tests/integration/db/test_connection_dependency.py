"""Integration tests for the per-request transaction boundary `get_connection` opens.

Three things are pinned here, each against the real Postgres. A handler that returns commits its
writes; a handler that raises leaves nothing behind; and a commit that fails answers an error
status rather than the success the client would otherwise already hold. The third is the
assertion that fails if `scope="function"` is dropped from the dependency: under FastAPI's default
request scope the commit runs after the response has been sent, so a failure there cannot change
the status the client received.

The commit failure is produced by a real deferred constraint rather than by patching the
connection, so the failure happens at COMMIT the way a deferred violation does in production.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.constants.error_codes import ErrorCode

COMMIT_PATH = "/test-only/connection/commit"
ROLLBACK_PATH = "/test-only/connection/rollback"
DEFERRED_CONFLICT_PATH = "/test-only/connection/deferred-conflict"

PASSWORD_HASH = "-".join(("test", "hash"))
HANDLER_FAILURE_MESSAGE = "the handler failed after it wrote"
PROBE_TABLE_NAME = "commit_failure_probe"

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]

CREATE_PROBE_TABLE_SQL = text(
    f"CREATE TABLE {PROBE_TABLE_NAME} ("
    "  value text NOT NULL,"
    f"  CONSTRAINT {PROBE_TABLE_NAME}_value_key UNIQUE (value) DEFERRABLE INITIALLY DEFERRED"
    ")"
)
DROP_PROBE_TABLE_SQL = text(f"DROP TABLE IF EXISTS {PROBE_TABLE_NAME}")
INSERT_PROBE_SQL = text("INSERT INTO commit_failure_probe (value) VALUES (:value)")
COUNT_PROBE_SQL = text("SELECT count(*) FROM commit_failure_probe WHERE value = :value")
INSERT_USER_SQL = text("INSERT INTO users (email, password_hash) VALUES (:email, :password_hash)")
COUNT_USERS_SQL = text("SELECT count(*) FROM users WHERE email = :email")


def build_unique_email() -> str:
    """Return an address no other test has used, so rows never collide across tests."""
    return f"boundary-{uuid.uuid4().hex}@example.test"


def build_test_only_router() -> APIRouter:
    """Return routes that commit, that raise after writing, and whose commit itself fails."""
    from app.db.session import get_connection  # noqa: PLC0415

    router = APIRouter()
    connection_dependency = Annotated[AsyncConnection, Depends(get_connection, scope="function")]

    @router.post(COMMIT_PATH)
    async def write_and_return(email: str, connection: connection_dependency) -> dict[str, str]:
        """Write a user within the request transaction."""
        await connection.execute(INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH})
        return {"email": email}

    @router.post(ROLLBACK_PATH)
    async def write_and_raise(email: str, connection: connection_dependency) -> dict[str, str]:
        """Write a user within the request transaction."""
        await connection.execute(INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH})
        raise RuntimeError(HANDLER_FAILURE_MESSAGE)

    @router.post(DEFERRED_CONFLICT_PATH)
    async def write_a_deferred_conflict(
        value: str, connection: connection_dependency
    ) -> dict[str, str]:
        """Write a duplicate whose constraint is checked only at commit."""
        await connection.execute(INSERT_PROBE_SQL, {"value": value})
        await connection.execute(INSERT_PROBE_SQL, {"value": value})
        return {"value": value}

    return router


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def probe_table(database_engine: AsyncEngine) -> AsyncIterator[None]:
    """Create the deferred-constraint table the commit-failure test writes to, and drop it."""
    async with database_engine.begin() as connection:
        await connection.execute(DROP_PROBE_TABLE_SQL)
        await connection.execute(CREATE_PROBE_TABLE_SQL)
    try:
        yield
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DROP_PROBE_TABLE_SQL)


def build_connection_client(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
) -> Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]:
    """Return a client factory bound to an app with the test-only router and a real database."""

    def open_connection_client() -> AbstractAsyncContextManager[httpx.AsyncClient]:
        """Build routes in the test body so missing imports are test failures."""
        application = build_server_app(
            test_only_router=build_test_only_router(), database_url=migrated_database_url
        )
        return build_api_client(application)

    return open_connection_client


async def count_users(engine: AsyncEngine, email: str) -> int:
    """Return how many user rows carry this address, read on its own connection."""
    async with engine.connect() as connection:
        return int(await connection.scalar(COUNT_USERS_SQL, {"email": email}) or 0)


@pytest.mark.integration
async def test_a_handler_that_returns_commits_its_write(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
    database_engine: AsyncEngine,
) -> None:
    """The transaction commits when the handler returns, so exactly one row survives."""
    connection_client = build_connection_client(
        build_server_app, build_api_client, migrated_database_url
    )
    email = build_unique_email()

    client_context = connection_client()
    try:
        async with client_context as client:
            response = await client.post(COMMIT_PATH, params={"email": email})

        assert response.status_code == 200, response.text
        assert await count_users(database_engine, email) == 1
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM users WHERE email = :email"), {"email": email}
            )


@pytest.mark.integration
async def test_a_handler_that_raises_after_writing_leaves_no_row(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
    database_engine: AsyncEngine,
) -> None:
    """The transaction rolls back when the handler raises, so the partial write is discarded."""
    connection_client = build_connection_client(
        build_server_app, build_api_client, migrated_database_url
    )
    email = build_unique_email()

    async with connection_client() as client:
        response = await client.post(ROLLBACK_PATH, params={"email": email})

    assert response.status_code == 500, response.text
    assert response.json()["code"] == ErrorCode.SERVER_INTERNAL_ERROR
    assert HANDLER_FAILURE_MESSAGE in response.json()["error"]
    assert await count_users(database_engine, email) == 0


@pytest.mark.integration
async def test_a_failed_commit_answers_an_error_rather_than_the_success_already_sent(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
    database_engine: AsyncEngine,
) -> None:
    """A deferred violation raised at COMMIT changes the response, and nothing is persisted.

    This is the assertion that fails when `scope="function"` is dropped: with the dependency at
    request scope the commit runs after the response is sent and the client keeps its 200.
    """
    connection_client = build_connection_client(
        build_server_app, build_api_client, migrated_database_url
    )
    client_context = connection_client()
    value = uuid.uuid4().hex

    async with probe_table(database_engine):
        async with client_context as client:
            response = await client.post(DEFERRED_CONFLICT_PATH, params={"value": value})

        assert response.status_code == 500, response.text
        assert response.json()["code"] == ErrorCode.SERVER_INTERNAL_ERROR
        async with database_engine.connect() as connection:
            assert await connection.scalar(COUNT_PROBE_SQL, {"value": value}) == 0
