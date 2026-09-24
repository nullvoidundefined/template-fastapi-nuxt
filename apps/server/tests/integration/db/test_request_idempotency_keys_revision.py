"""The revision creating `request_idempotency_keys`: its key, its cascade, its index, its reversal.

The claim protocol leans on three schema facts that no request-level test states directly: one
row per `(key, user_id)`, so the claim insert can conflict; `ON DELETE CASCADE` from the user, so
deleting an account leaves no orphaned claims; and an index on `created_at`, so the slice 08
cleanup finds rows older than twenty-four hours without scanning. Each is read from Postgres.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

REVISION_BEFORE_KEYS = "20260924_0004"
PASSWORD_HASH = "-".join(("test", "hash"))

AlembicConfigFactory = Callable[[str], Config]

TABLE_EXISTS_SQL = text("SELECT to_regclass('request_idempotency_keys') IS NOT NULL")
STATE_LABELS_SQL = text(
    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
    "WHERE t.typname = 'request_idempotency_key_state' ORDER BY e.enumsortorder"
)
CREATED_AT_INDEX_SQL = text(
    "SELECT indexdef FROM pg_indexes WHERE tablename = 'request_idempotency_keys' "
    "AND indexname = 'ix_request_idempotency_keys_created_at'"
)
INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_CLAIM_SQL = text(
    "INSERT INTO request_idempotency_keys (key, user_id, request_method, request_path, "
    "request_body_hash, state, locked_until, claim_token) VALUES (:key, :user_id, 'POST', "
    "'/v1/example', 'hash', 'in_progress', now() + interval '60 seconds', gen_random_uuid())"
)
COUNT_CLAIMS_SQL = text("SELECT count(*) FROM request_idempotency_keys WHERE user_id = :user_id")
DELETE_USER_SQL = text("DELETE FROM users WHERE id = :user_id")


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def seed_user(engine: AsyncEngine) -> uuid.UUID:
    """Commit one user and return its id."""
    async with engine.begin() as connection:
        user_id = await connection.scalar(
            INSERT_USER_SQL,
            {"email": f"keys-{uuid.uuid4().hex}@example.test", "password_hash": PASSWORD_HASH},
        )
    return uuid.UUID(str(user_id))


@pytest.mark.integration
async def test_the_table_holds_one_claim_per_key_and_user_and_cascades_with_the_user(
    database_engine: AsyncEngine,
) -> None:
    """A second claim on the same key and user is refused, and deleting the user removes both."""
    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL), "request_idempotency_keys is missing"
        assert list((await connection.execute(STATE_LABELS_SQL)).scalars()) == [
            "in_progress",
            "completed",
        ]
        assert (await connection.execute(CREATED_AT_INDEX_SQL)).one_or_none() is not None
    user_id = await seed_user(database_engine)
    other_user_id = await seed_user(database_engine)
    try:
        async with database_engine.begin() as connection:
            await connection.execute(INSERT_CLAIM_SQL, {"key": "k", "user_id": user_id})
            await connection.execute(INSERT_CLAIM_SQL, {"key": "k", "user_id": other_user_id})
        with pytest.raises(IntegrityError):
            async with database_engine.begin() as connection:
                await connection.execute(INSERT_CLAIM_SQL, {"key": "k", "user_id": user_id})
        async with database_engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
            assert await connection.scalar(COUNT_CLAIMS_SQL, {"user_id": user_id}) == 0
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
            await connection.execute(DELETE_USER_SQL, {"user_id": other_user_id})


@pytest.mark.integration
async def test_the_keys_revision_downgrades_leaving_neither_table_nor_enum(
    migrated_database_url: str,
    alembic_config_factory: AlembicConfigFactory,
    database_engine: AsyncEngine,
) -> None:
    """Downgrading one step removes the table and its state enum; the upgrade restores both."""
    config = alembic_config_factory(migrated_database_url)
    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL), "request_idempotency_keys is missing"
    try:
        await asyncio.to_thread(command.downgrade, config, REVISION_BEFORE_KEYS)
        async with database_engine.connect() as connection:
            assert not await connection.scalar(TABLE_EXISTS_SQL)
            assert list((await connection.execute(STATE_LABELS_SQL)).scalars()) == []
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
    async with database_engine.connect() as connection:
        assert await connection.scalar(TABLE_EXISTS_SQL)
