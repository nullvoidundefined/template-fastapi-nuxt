"""The slice 05 revision that gives every user a role, and backfills the users that already exist.

The data model says `role` is the enum `user_role` with the values `member` and `admin`, not null,
defaulting to `member`, and added by a revision that backfills every existing row. The backfill is
the part a later test cannot observe by accident, so the reversibility test inserts a user while
the schema has no role at all and then proves the upgrade gave that user `member`.

Every assertion reads the real Postgres through raw SQL rather than the metadata, because the
schema the revision produced is what is under test.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import cast

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

REVISION_BEFORE_ROLE = "20260924_0003"
PASSWORD_HASH = "-".join(("test", "hash"))

AlembicConfigFactory = Callable[[str], Config]

ENUM_LABELS_SQL = text(
    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
    "WHERE t.typname = 'user_role' ORDER BY e.enumsortorder"
)
ROLE_COLUMN_SQL = text(
    "SELECT is_nullable, column_default, udt_name FROM information_schema.columns "
    "WHERE table_name = 'users' AND column_name = 'role'"
)
INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
READ_ROLE_SQL = text("SELECT role::text FROM users WHERE id = :user_id")
SET_ROLE_SQL = text("UPDATE users SET role = :role WHERE id = :user_id")
DELETE_USER_SQL = text("DELETE FROM users WHERE id = :user_id")


async def read_role(connection: AsyncConnection, user_id: uuid.UUID) -> str | None:
    """Return the user's role, asserting first that the column exists at all."""
    assert (await connection.execute(ROLE_COLUMN_SQL)).one_or_none(), "users has no role column"
    # read_role's SQL selects role::text, so the scalar is always a str or None; cast narrows
    # the driver's Any return to that known shape (R-401: not weakening the assertion).
    return cast("str | None", await connection.scalar(READ_ROLE_SQL, {"user_id": user_id}))


def build_unique_email() -> str:
    """Return an address no other test has used."""
    return f"role-revision-{uuid.uuid4().hex}@example.test"


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_role_is_a_not_null_user_role_enum_defaulting_to_member(
    database_engine: AsyncEngine,
) -> None:
    """The column is the `user_role` enum, member then admin, not null, with a member default."""
    async with database_engine.connect() as connection:
        labels = list((await connection.execute(ENUM_LABELS_SQL)).scalars())
        column = (await connection.execute(ROLE_COLUMN_SQL)).one_or_none()

    assert labels == ["member", "admin"]
    assert column is not None, "users has no role column"
    assert column.is_nullable == "NO"
    assert column.udt_name == "user_role"
    assert column.column_default.startswith("'member'")


@pytest.mark.integration
async def test_a_user_inserted_without_a_role_is_a_member_and_no_third_role_exists(
    database_engine: AsyncEngine,
) -> None:
    """A new row reads back as `member`, and a value outside the enum is refused."""
    async with database_engine.begin() as connection:
        user_id = await connection.scalar(
            INSERT_USER_SQL, {"email": build_unique_email(), "password_hash": PASSWORD_HASH}
        )
    try:
        async with database_engine.connect() as connection:
            assert await read_role(connection, user_id) == "member"
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(SET_ROLE_SQL, {"role": "owner", "user_id": user_id})
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})


@pytest.mark.integration
async def test_the_role_revision_backfills_existing_users_and_downgrades_cleanly(
    migrated_database_url: str,
    alembic_config_factory: AlembicConfigFactory,
    database_engine: AsyncEngine,
) -> None:
    """A user that existed before the revision is a member after it, and the downgrade drops both.

    The upgrade is restored in `finally`, because every later test in the run expects head.
    """
    config = alembic_config_factory(migrated_database_url)
    user_id = None
    try:
        await asyncio.to_thread(command.downgrade, config, REVISION_BEFORE_ROLE)
        async with database_engine.connect() as connection:
            assert (await connection.execute(ROLE_COLUMN_SQL)).one_or_none() is None
            assert list((await connection.execute(ENUM_LABELS_SQL)).scalars()) == []
        async with database_engine.begin() as connection:
            user_id = await connection.scalar(
                INSERT_USER_SQL, {"email": build_unique_email(), "password_hash": PASSWORD_HASH}
            )
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database_engine.connect() as connection:
            assert await read_role(connection, user_id) == "member"
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
        if user_id is not None:
            async with database_engine.begin() as connection:
                await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
