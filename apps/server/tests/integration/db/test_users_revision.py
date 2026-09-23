"""Integration tests for the first revision: reversibility, the trigger, and the unique index.

Every assertion here reads the real Postgres through raw SQL rather than through the metadata in
`app/db/tables.py`, because what is under test is the schema the migration produced. A test that
asked the metadata whether the column exists would pass on a revision that never ran.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TRIGGER_FUNCTION_NAME = "set_updated_at"
USERS_TABLE_NAME = "users"
PASSWORD_HASH = "-".join(("test", "hash"))
UPDATED_PASSWORD_HASH = "-".join(("updated", "test", "hash"))

AlembicConfigFactory = Callable[[str], Config]

TABLE_EXISTS_SQL = text("SELECT to_regclass(:qualified_name) IS NOT NULL")
FUNCTION_EXISTS_SQL = text("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = :function_name)")
INSERT_USER_SQL = text("INSERT INTO users (email, password_hash) VALUES (:email, :password_hash)")
READ_TIMESTAMPS_SQL = text("SELECT created_at, updated_at FROM users WHERE email = :email")
UPDATE_PASSWORD_SQL = text("UPDATE users SET password_hash = :password_hash WHERE email = :email")


def build_unique_email() -> str:
    """Return an address no other test has used, so rows never collide across tests."""
    return f"revision-{uuid.uuid4().hex}@example.test"


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_the_first_revision_downgrades_to_base_leaving_no_table_and_no_function(
    migrated_database_url: str,
    alembic_config_factory: AlembicConfigFactory,
    database_engine: AsyncEngine,
) -> None:
    """`downgrade base` removes both the users table and the shared trigger function.

    The upgrade is restored in `finally`, because the session-scoped fixture migrated the database
    once and every later test in this run would otherwise see an empty schema.
    """
    assert (Path(__file__).resolve().parents[3] / "alembic.ini").is_file()
    assert list((Path(__file__).resolve().parents[3] / "migrations/versions").glob("*.py"))
    config = alembic_config_factory(migrated_database_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "base")
    try:
        async with database_engine.connect() as connection:
            table_exists = await connection.scalar(
                TABLE_EXISTS_SQL, {"qualified_name": USERS_TABLE_NAME}
            )
            function_exists = await connection.scalar(
                FUNCTION_EXISTS_SQL, {"function_name": TRIGGER_FUNCTION_NAME}
            )
        assert table_exists is False
        assert function_exists is False
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")

    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL, {"qualified_name": USERS_TABLE_NAME})
        assert await connection.scalar(
            FUNCTION_EXISTS_SQL, {"function_name": TRIGGER_FUNCTION_NAME}
        )


@pytest.mark.integration
async def test_updating_a_user_moves_updated_at_and_leaves_created_at_unchanged(
    database_engine: AsyncEngine,
) -> None:
    """The set_updated_at trigger fires on UPDATE, so updated_at moves and created_at does not.

    The insert and the update run in separate transactions on purpose: `now()` is the transaction
    timestamp, so a trigger that fired inside the inserting transaction would write the same
    instant and the assertion could not tell a working trigger from a missing one.
    """
    from app.db.tables import metadata, users  # noqa: PLC0415

    assert users.metadata is metadata
    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL, {"qualified_name": USERS_TABLE_NAME})
    email = build_unique_email()
    try:
        async with database_engine.begin() as connection:
            await connection.execute(
                INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH}
            )
        async with database_engine.connect() as connection:
            inserted = (await connection.execute(READ_TIMESTAMPS_SQL, {"email": email})).one()

        async with database_engine.begin() as connection:
            await connection.execute(
                UPDATE_PASSWORD_SQL, {"email": email, "password_hash": UPDATED_PASSWORD_HASH}
            )
        async with database_engine.connect() as connection:
            updated = (await connection.execute(READ_TIMESTAMPS_SQL, {"email": email})).one()

        assert updated.created_at == inserted.created_at
        assert updated.updated_at > inserted.updated_at
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM users WHERE lower(email) = lower(:email)"), {"email": email}
            )


@pytest.mark.integration
async def test_two_emails_differing_only_in_case_violate_the_unique_index(
    database_engine: AsyncEngine,
) -> None:
    """The unique index on lower(email) makes a mixed-case duplicate a duplicate."""
    from app.db.tables import metadata, users  # noqa: PLC0415

    assert users.metadata is metadata
    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL, {"qualified_name": USERS_TABLE_NAME})
    email = build_unique_email()
    try:
        async with database_engine.begin() as connection:
            await connection.execute(
                INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH}
            )

        with pytest.raises(IntegrityError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    INSERT_USER_SQL, {"email": email.upper(), "password_hash": PASSWORD_HASH}
                )
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM users WHERE lower(email) = lower(:email)"), {"email": email}
            )
