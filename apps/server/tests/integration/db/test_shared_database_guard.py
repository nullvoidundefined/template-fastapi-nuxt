"""The integration suite refuses a database that another client is connected to (IAN-340).

Several revision tests downgrade and re-upgrade the schema. Run against the database the compose
stack serves, that invalidates the prepared statements the running API holds in its connection
pool, so the next request on each pooled connection answers 500 with "cached plan must not change
result type" and the one after it succeeds. That is how the pre-push Playwright step failed on the
first push and passed on the second. These tests hold a second connection open, standing in for
the stack's pool, and prove the guard sees it and refuses the database while it is held. They also
prove the guard ignores a Postgres health probe, which CI runs against the same database every few
seconds, and that it gives up on a host that never answers rather than hanging the run.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration import conftest as integration_conftest
from tests.integration.conftest import (
    list_other_database_clients,
    refuse_shared_test_database,
)

# A TEST-NET-3 address (RFC 5737): nothing answers there, so a connect attempt can only time out.
SILENT_DATABASE_URL = "postgresql+asyncpg://app@203.0.113.1:5432/app"
SHORT_CONNECT_TIMEOUT_SECONDS = 0.5
GUARD_GIVE_UP_CEILING_SECONDS = 5.0


@asynccontextmanager
async def hold_connection(database_url: str, application_name: str) -> AsyncIterator[None]:
    """Hold one open connection to the database under the given application name."""
    holder_engine = create_async_engine(
        database_url, connect_args={"server_settings": {"application_name": application_name}}
    )
    try:
        async with holder_engine.connect() as holder_connection:
            await holder_connection.execute(text("SELECT 1"))
            yield
    finally:
        await holder_engine.dispose()


@pytest.mark.integration
async def test_ian340_a_held_connection_is_listed_as_another_client(database_url: str) -> None:
    """A connection another process holds is listed while it is open, and not after it closes."""
    holder_name = f"ian340-holder-{uuid.uuid4().hex}"
    async with hold_connection(database_url, holder_name):
        clients_while_held = await list_other_database_clients(database_url)
    clients_after_release = await list_other_database_clients(database_url)
    assert holder_name in clients_while_held
    assert holder_name not in clients_after_release


@pytest.mark.integration
async def test_ian340_a_pg_isready_health_probe_is_not_counted(database_url: str) -> None:
    """pg_isready connects under its own name every few seconds in CI, and must not count."""
    async with hold_connection(database_url, "pg_isready"):
        clients_while_held = await list_other_database_clients(database_url)
    assert "pg_isready" not in clients_while_held


@pytest.mark.integration
async def test_ian340_a_database_another_client_holds_is_refused_with_the_remedy(
    database_url: str,
) -> None:
    """The guard fails the run, naming the database and how to create a dedicated one."""
    async with hold_connection(database_url, f"ian340-holder-{uuid.uuid4().hex}"):
        with pytest.raises(pytest.fail.Exception) as refusal:
            await asyncio.to_thread(refuse_shared_test_database, database_url)
    refusal_message = str(refusal.value)
    database_name = database_url.rsplit("/", 1)[-1]
    assert f'"{database_name}"' in refusal_message
    assert "createdb" in refusal_message


def test_ian340_a_host_that_never_answers_is_given_up_on_without_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard stops waiting after its connect timeout and leaves the outage to the tests."""
    monkeypatch.setattr(
        integration_conftest, "GUARD_CONNECT_TIMEOUT_SECONDS", SHORT_CONNECT_TIMEOUT_SECONDS
    )
    started_at = time.monotonic()
    refuse_shared_test_database(SILENT_DATABASE_URL)
    assert time.monotonic() - started_at < GUARD_GIVE_UP_CEILING_SECONDS
