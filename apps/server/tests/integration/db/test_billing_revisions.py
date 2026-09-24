"""The two billing revisions: `user_subscriptions` and the `billing_webhook_events` ledger.

The webhook handlers lean on schema facts that no request-level test states directly: one
subscription row per user, unique Stripe identifiers, a status enum holding the Express template's
values, `ON DELETE CASCADE` from the user, an `updated_at` the shared trigger maintains, and one
ledger row per Stripe event. Each is read back from Postgres, and each revision is shown to
downgrade cleanly, table and enum both.
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

REVISION_BEFORE_SUBSCRIPTIONS = "20260924_0005"
REVISION_BEFORE_LEDGER = "20260924_0006"
PASSWORD_HASH = "-".join(("test", "hash"))
EXPRESS_SUBSCRIPTION_STATUSES = [
    "active",
    "canceled",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "paused",
    "trialing",
    "unpaid",
]

AlembicConfigFactory = Callable[[str], Config]

SUBSCRIPTIONS_EXISTS_SQL = text("SELECT to_regclass('user_subscriptions') IS NOT NULL")
LEDGER_EXISTS_SQL = text("SELECT to_regclass('billing_webhook_events') IS NOT NULL")
ENUM_LABELS_SQL = text(
    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
    "WHERE t.typname = :type_name ORDER BY e.enumsortorder"
)
INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_SUBSCRIPTION_SQL = text(
    "INSERT INTO user_subscriptions (user_id, stripe_customer_id, stripe_subscription_id) "
    "VALUES (:user_id, :customer_id, :subscription_id) RETURNING id"
)
READ_SUBSCRIPTION_SQL = text(
    "SELECT status::text AS status, is_canceling_at_period_end, plan_id, current_period_start, "
    "current_period_end, created_at, updated_at FROM user_subscriptions WHERE user_id = :user_id"
)
TOUCH_SUBSCRIPTION_SQL = text(
    "UPDATE user_subscriptions SET plan_id = 'price_x' WHERE user_id = :u"
)
COUNT_SUBSCRIPTIONS_SQL = text("SELECT count(*) FROM user_subscriptions WHERE user_id = :user_id")
DELETE_USER_SQL = text("DELETE FROM users WHERE id = :user_id")
INSERT_LEDGER_SQL = text(
    "INSERT INTO billing_webhook_events (stripe_event_id, event_type, status) "
    "VALUES (:event_id, 'checkout.session.completed', 'claimed') "
    "RETURNING id, attempted_at, processed_at"
)
DELETE_LEDGER_SQL = text("DELETE FROM billing_webhook_events WHERE stripe_event_id = :event_id")
COLUMN_SHAPE_SQL = text(
    "SELECT data_type, is_nullable FROM information_schema.columns "
    "WHERE table_name = :table_name AND column_name = :column_name"
)


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
            {"email": f"billing-{uuid.uuid4().hex}@example.test", "password_hash": PASSWORD_HASH},
        )
    return uuid.UUID(str(user_id))


def make_stripe_id(prefix: str) -> str:
    """Return a unique Stripe-shaped identifier with the given prefix."""
    return f"{prefix}_{uuid.uuid4().hex}"


@pytest.mark.integration
async def test_user_subscriptions_holds_one_row_per_user_with_express_statuses(
    database_engine: AsyncEngine,
) -> None:
    """One row per user, unique Stripe ids, defaults, the trigger, and the cascade from users."""
    async with database_engine.connect() as connection:
        assert await connection.scalar(SUBSCRIPTIONS_EXISTS_SQL), "user_subscriptions is missing"
        labels = await connection.execute(
            ENUM_LABELS_SQL, {"type_name": "user_subscription_status"}
        )
        assert list(labels.scalars()) == EXPRESS_SUBSCRIPTION_STATUSES
    user_id = await seed_user(database_engine)
    other_user_id = await seed_user(database_engine)
    customer_id = make_stripe_id("cus")
    subscription_id = make_stripe_id("sub")
    try:
        async with database_engine.begin() as connection:
            await connection.execute(
                INSERT_SUBSCRIPTION_SQL,
                {
                    "user_id": user_id,
                    "customer_id": customer_id,
                    "subscription_id": subscription_id,
                },
            )
        async with database_engine.connect() as connection:
            stored = (await connection.execute(READ_SUBSCRIPTION_SQL, {"user_id": user_id})).one()
        assert stored.status == "incomplete"
        assert stored.is_canceling_at_period_end is False
        assert stored.plan_id is None
        assert stored.current_period_start is None
        assert stored.current_period_end is None

        duplicates = [
            {"user_id": user_id, "customer_id": make_stripe_id("cus"), "subscription_id": None},
            {"user_id": other_user_id, "customer_id": customer_id, "subscription_id": None},
            {
                "user_id": other_user_id,
                "customer_id": make_stripe_id("cus"),
                "subscription_id": subscription_id,
            },
        ]
        for duplicate in duplicates:
            with pytest.raises(IntegrityError):
                async with database_engine.begin() as connection:
                    await connection.execute(INSERT_SUBSCRIPTION_SQL, duplicate)

        async with database_engine.begin() as connection:
            await connection.execute(TOUCH_SUBSCRIPTION_SQL, {"u": user_id})
        async with database_engine.connect() as connection:
            touched = (await connection.execute(READ_SUBSCRIPTION_SQL, {"user_id": user_id})).one()
        assert touched.plan_id == "price_x"
        assert touched.updated_at > stored.updated_at

        async with database_engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
            assert await connection.scalar(COUNT_SUBSCRIPTIONS_SQL, {"user_id": user_id}) == 0
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
            await connection.execute(DELETE_USER_SQL, {"user_id": other_user_id})


@pytest.mark.integration
async def test_user_subscriptions_records_the_last_applied_stripe_event_time(
    database_engine: AsyncEngine,
) -> None:
    """A nullable timestamptz holds the `created` of the subscription event last applied.

    It is null until a subscription event is applied, which is what lets a row seeded by checkout
    take the first subscription event whatever its time.
    """
    async with database_engine.connect() as connection:
        shape = (
            await connection.execute(
                COLUMN_SHAPE_SQL,
                {
                    "column_name": "last_stripe_event_created_at",
                    "table_name": "user_subscriptions",
                },
            )
        ).one_or_none()

    assert shape is not None, "user_subscriptions.last_stripe_event_created_at is missing"
    assert shape.data_type == "timestamp with time zone"
    assert shape.is_nullable == "YES"


@pytest.mark.integration
async def test_billing_webhook_events_holds_one_row_per_stripe_event(
    database_engine: AsyncEngine,
) -> None:
    """The ledger's status enum, its attempted_at default, and its unique Stripe event id."""
    async with database_engine.connect() as connection:
        assert await connection.scalar(LEDGER_EXISTS_SQL), "billing_webhook_events is missing"
        labels = await connection.execute(
            ENUM_LABELS_SQL, {"type_name": "billing_webhook_event_status"}
        )
        assert list(labels.scalars()) == ["claimed", "processed", "failed"]
    event_id = make_stripe_id("evt")
    try:
        async with database_engine.begin() as connection:
            inserted = (await connection.execute(INSERT_LEDGER_SQL, {"event_id": event_id})).one()
        assert inserted.attempted_at is not None
        assert inserted.processed_at is None
        with pytest.raises(IntegrityError):
            async with database_engine.begin() as connection:
                await connection.execute(INSERT_LEDGER_SQL, {"event_id": event_id})
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DELETE_LEDGER_SQL, {"event_id": event_id})


@pytest.mark.integration
async def test_the_billing_revisions_downgrade_leaving_neither_tables_nor_enums(
    migrated_database_url: str,
    alembic_config_factory: AlembicConfigFactory,
    database_engine: AsyncEngine,
) -> None:
    """Each downgrade removes its table and enum; the upgrade back to head restores both."""
    config = alembic_config_factory(migrated_database_url)
    async with database_engine.connect() as connection:
        assert await connection.scalar(LEDGER_EXISTS_SQL), "billing_webhook_events is missing"
    try:
        await asyncio.to_thread(command.downgrade, config, REVISION_BEFORE_LEDGER)
        async with database_engine.connect() as connection:
            assert not await connection.scalar(LEDGER_EXISTS_SQL)
            assert await connection.scalar(SUBSCRIPTIONS_EXISTS_SQL)
            ledger_labels = await connection.execute(
                ENUM_LABELS_SQL, {"type_name": "billing_webhook_event_status"}
            )
            assert list(ledger_labels.scalars()) == []
        await asyncio.to_thread(command.downgrade, config, REVISION_BEFORE_SUBSCRIPTIONS)
        async with database_engine.connect() as connection:
            assert not await connection.scalar(SUBSCRIPTIONS_EXISTS_SQL)
            status_labels = await connection.execute(
                ENUM_LABELS_SQL, {"type_name": "user_subscription_status"}
            )
            assert list(status_labels.scalars()) == []
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
    async with database_engine.connect() as connection:
        assert await connection.scalar(SUBSCRIPTIONS_EXISTS_SQL)
        assert await connection.scalar(LEDGER_EXISTS_SQL)
