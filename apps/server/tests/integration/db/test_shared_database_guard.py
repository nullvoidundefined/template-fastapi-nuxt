"""The integration suite refuses a database that another client is connected to (IAN-340).

Several revision tests downgrade and re-upgrade the schema. Run against the database the compose
stack serves, that invalidates the prepared statements the running API holds in its connection
pool, so the next request on each pooled connection answers 500 with "cached plan must not change
result type" and the one after it succeeds. That is how the pre-push Playwright step failed on the
first push and passed on the second. These tests hold a second connection open, standing in for
the stack's pool, and prove the guard counts it and refuses the database while it is held.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import (
    count_other_database_clients,
    refuse_shared_test_database,
)


@pytest.mark.integration
async def test_ian340_a_held_connection_is_counted_as_another_client(database_url: str) -> None:
    """Opening one more connection to the database raises the count by exactly one."""
    count_before = await count_other_database_clients(database_url)
    holder_engine = create_async_engine(database_url)
    try:
        async with holder_engine.connect() as holder_connection:
            await holder_connection.execute(text("SELECT 1"))
            count_while_held = await count_other_database_clients(database_url)
    finally:
        await holder_engine.dispose()
    assert count_while_held == count_before + 1


@pytest.mark.integration
async def test_ian340_a_database_another_client_holds_is_refused_with_the_remedy(
    database_url: str,
) -> None:
    """The guard fails the run, naming the database and how to create a dedicated one."""
    holder_engine = create_async_engine(database_url)
    try:
        async with holder_engine.connect() as holder_connection:
            await holder_connection.execute(text("SELECT 1"))
            with pytest.raises(pytest.fail.Exception) as refusal:
                await asyncio.to_thread(refuse_shared_test_database, database_url)
    finally:
        await holder_engine.dispose()
    refusal_message = str(refusal.value)
    database_name = database_url.rsplit("/", 1)[-1]
    assert f'"{database_name}"' in refusal_message
    assert "createdb" in refusal_message
