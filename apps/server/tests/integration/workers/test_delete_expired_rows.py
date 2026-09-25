"""B-26 integration tests for the hourly cleanup job in app/workers/jobs/delete_expired_rows.py.

Each test seeds rows into the real Postgres with their expiry or age set by the database's own
clock, runs the job with the context arq would pass it (the engine and a job ID), and reads the
tables back. The seeded rows carry a per-test marker, a fresh user or a unique prefix, so the
assertions look only at this test's rows while other tests' leftovers sit in the same tables.

The job and the repository functions are imported inside each test body, so a missing module
fails that test rather than the collection of the file.
"""

import importlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from structlog.contextvars import clear_contextvars, get_contextvars, merge_contextvars

JOB_MODULE = "app.workers.jobs.delete_expired_rows"
CLEANUP_JOB_ID = "cron:delete_expired_rows:1"
DELETED_EVENT_NAME = "expired_rows_deleted"
SESSIONS_TABLE = "user_sessions"
IDEMPOTENCY_KEYS_TABLE = "request_idempotency_keys"
WEBHOOK_EVENTS_TABLE = "billing_webhook_events"
CLEANED_TABLES = {SESSIONS_TABLE, IDEMPOTENCY_KEYS_TABLE, WEBHOOK_EVENTS_TABLE}
PRODUCTION_BATCH_SIZE = 1000
BACKLOG_ROW_COUNT = PRODUCTION_BATCH_SIZE + 3
PASSWORD_HASH = "-".join(("test", "hash"))

INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_SESSIONS_SQL = text(
    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
    "SELECT :user_id, :marker || '-' || n, now() + CAST(:expires_in AS interval) "
    "FROM generate_series(1, :row_count) AS n"
)
INSERT_IDEMPOTENCY_KEYS_SQL = text(
    "INSERT INTO request_idempotency_keys (key, user_id, request_method, request_path, "
    "request_body_hash, state, locked_until, claim_token, created_at) "
    "SELECT :marker || '-' || n, :user_id, 'POST', '/v1/test', 'body-hash', 'completed', now(), "
    "gen_random_uuid(), now() - CAST(:age AS interval) "
    "FROM generate_series(1, :row_count) AS n"
)
INSERT_WEBHOOK_EVENTS_SQL = text(
    "INSERT INTO billing_webhook_events (stripe_event_id, event_type, status, attempted_at) "
    "SELECT :marker || '-' || n, 'checkout.session.completed', 'processed', "
    "now() - CAST(:age AS interval) FROM generate_series(1, :row_count) AS n"
)
COUNT_SESSIONS_SQL = text(
    "SELECT count(*) FROM user_sessions WHERE token_hash LIKE :marker || '-%'"
)
COUNT_IDEMPOTENCY_KEYS_SQL = text(
    "SELECT count(*) FROM request_idempotency_keys WHERE key LIKE :marker || '-%'"
)
COUNT_WEBHOOK_EVENTS_SQL = text(
    "SELECT count(*) FROM billing_webhook_events WHERE stripe_event_id LIKE :marker || '-%'"
)

StaleRowSeeder = Callable[[AsyncConnection, uuid.UUID, str, int], Awaitable[None]]


@pytest.fixture(autouse=True)
def empty_structlog_context() -> Iterator[None]:
    """Start and end every test with an empty structlog context, so no key leaks across tests."""
    clear_contextvars()
    yield
    clear_contextvars()


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_user_id(database_engine: AsyncEngine) -> uuid.UUID:
    """Insert one user the seeded sessions and idempotency keys belong to, and return its id."""
    async with database_engine.begin() as connection:
        user_id = await connection.scalar(
            INSERT_USER_SQL,
            {"email": f"cleanup-{uuid.uuid4()}@example.test", "password_hash": PASSWORD_HASH},
        )
    assert isinstance(user_id, uuid.UUID)
    return user_id


def build_marker(label: str) -> str:
    """Return a prefix unique to this test run, so its rows are told apart from any other."""
    return f"cleanup-{label}-{uuid.uuid4()}"


async def seed_sessions(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    marker: str,
    row_count: int,
    expires_in: timedelta,
) -> None:
    """Insert sessions expiring `expires_in` from the database's now (negative: already expired)."""
    await connection.execute(
        INSERT_SESSIONS_SQL,
        {"user_id": user_id, "marker": marker, "expires_in": expires_in, "row_count": row_count},
    )


async def seed_idempotency_keys(
    connection: AsyncConnection, user_id: uuid.UUID, marker: str, row_count: int, age: timedelta
) -> None:
    """Insert completed idempotency keys created `age` before the database's now."""
    await connection.execute(
        INSERT_IDEMPOTENCY_KEYS_SQL,
        {"user_id": user_id, "marker": marker, "age": age, "row_count": row_count},
    )


async def seed_webhook_events(
    connection: AsyncConnection, marker: str, row_count: int, age: timedelta
) -> None:
    """Insert processed webhook ledger rows last attempted `age` before the database's now."""
    await connection.execute(
        INSERT_WEBHOOK_EVENTS_SQL, {"marker": marker, "age": age, "row_count": row_count}
    )


async def seed_expired_sessions(
    connection: AsyncConnection, user_id: uuid.UUID, marker: str, row_count: int
) -> None:
    """Insert sessions that expired a minute ago."""
    await seed_sessions(connection, user_id, marker, row_count, -timedelta(minutes=1))


async def seed_stale_idempotency_keys(
    connection: AsyncConnection, user_id: uuid.UUID, marker: str, row_count: int
) -> None:
    """Insert idempotency keys twenty-five hours old, past the twenty-four hour window."""
    await seed_idempotency_keys(connection, user_id, marker, row_count, timedelta(hours=25))


async def seed_stale_webhook_events(
    connection: AsyncConnection, _user_id: uuid.UUID, marker: str, row_count: int
) -> None:
    """Insert webhook ledger rows thirty-one days old, past the thirty-day retention."""
    await seed_webhook_events(connection, marker, row_count, timedelta(days=31))


async def count_seeded_rows(engine: AsyncEngine, count_sql: TextClause, marker: str) -> int:
    """Return how many rows carrying this marker are still in the table the query reads."""
    async with engine.connect() as connection:
        row_count = await connection.scalar(count_sql, {"marker": marker})
    return int(row_count or 0)


async def run_cleanup_job(engine: AsyncEngine) -> dict[str, int]:
    """Run the job with the context arq would pass it and return its per-table counts."""
    job_module = importlib.import_module(JOB_MODULE)
    worker_context = {"engine": engine, "job_id": CLEANUP_JOB_ID}
    deleted_counts: dict[str, int] = await job_module.delete_expired_rows(worker_context)
    return deleted_counts


async def test_b26_delete_expired_rows_deletes_only_the_expired_rows_of_each_table(
    database_engine: AsyncEngine, seeded_user_id: uuid.UUID
) -> None:
    """B-26: expired sessions, day-old keys, and month-old ledger rows go; every live row stays."""
    markers = {name: build_marker(name) for name in ("expired", "live")}
    async with database_engine.begin() as connection:
        await seed_sessions(
            connection, seeded_user_id, markers["expired"], 2, -timedelta(minutes=1)
        )
        await seed_sessions(connection, seeded_user_id, markers["live"], 2, timedelta(days=1))
        await seed_idempotency_keys(
            connection, seeded_user_id, markers["expired"], 2, timedelta(hours=25)
        )
        await seed_idempotency_keys(
            connection, seeded_user_id, markers["live"], 2, timedelta(hours=23)
        )
        await seed_webhook_events(connection, markers["expired"], 2, timedelta(days=31))
        await seed_webhook_events(connection, markers["live"], 2, timedelta(days=29))

    deleted_counts = await run_cleanup_job(database_engine)

    count_queries = (COUNT_SESSIONS_SQL, COUNT_IDEMPOTENCY_KEYS_SQL, COUNT_WEBHOOK_EVENTS_SQL)
    for count_sql in count_queries:
        assert await count_seeded_rows(database_engine, count_sql, markers["expired"]) == 0
        assert await count_seeded_rows(database_engine, count_sql, markers["live"]) == 2
    assert set(deleted_counts) == CLEANED_TABLES
    assert all(deleted_counts[table] >= 2 for table in CLEANED_TABLES)


async def test_b26_delete_expired_rows_works_through_a_backlog_larger_than_one_batch(
    database_engine: AsyncEngine, seeded_user_id: uuid.UUID
) -> None:
    """B-26: a backlog of 1000 + 3 rows per table is deleted in full, so more than one batch ran."""
    marker = build_marker("backlog")
    async with database_engine.begin() as connection:
        await seed_expired_sessions(connection, seeded_user_id, marker, BACKLOG_ROW_COUNT)
        await seed_stale_idempotency_keys(connection, seeded_user_id, marker, BACKLOG_ROW_COUNT)
        await seed_stale_webhook_events(connection, seeded_user_id, marker, BACKLOG_ROW_COUNT)

    deleted_counts = await run_cleanup_job(database_engine)

    for count_sql in (COUNT_SESSIONS_SQL, COUNT_IDEMPOTENCY_KEYS_SQL, COUNT_WEBHOOK_EVENTS_SQL):
        assert await count_seeded_rows(database_engine, count_sql, marker) == 0
    assert all(deleted_counts[table] >= BACKLOG_ROW_COUNT for table in CLEANED_TABLES)


async def test_b26_delete_expired_rows_deletes_nothing_on_a_second_run(
    database_engine: AsyncEngine, seeded_user_id: uuid.UUID
) -> None:
    """B-26: the job is idempotent; a second run deletes nothing and keeps the live rows."""
    markers = {name: build_marker(name) for name in ("expired", "live")}
    async with database_engine.begin() as connection:
        await seed_expired_sessions(connection, seeded_user_id, markers["expired"], 3)
        await seed_sessions(connection, seeded_user_id, markers["live"], 1, timedelta(hours=1))

    await run_cleanup_job(database_engine)
    second_deleted_counts = await run_cleanup_job(database_engine)

    # Exact, because the integration suite runs serially against one database. If it is ever
    # sharded, these cleanup tests need a database per worker rather than looser assertions.
    assert second_deleted_counts == dict.fromkeys(CLEANED_TABLES, 0)
    assert await count_seeded_rows(database_engine, COUNT_SESSIONS_SQL, markers["live"]) == 1


async def test_b26_delete_expired_rows_logs_one_line_per_table_carrying_the_job_id(
    database_engine: AsyncEngine, seeded_user_id: uuid.UUID
) -> None:
    """B-26 and R-341: one structured line per table with its deleted count and arq's job_id."""
    marker = build_marker("logged")
    async with database_engine.begin() as connection:
        await seed_expired_sessions(connection, seeded_user_id, marker, 1)

    with structlog.testing.capture_logs(processors=[merge_contextvars]) as captured_events:
        deleted_counts = await run_cleanup_job(database_engine)

    deleted_events = [event for event in captured_events if event["event"] == DELETED_EVENT_NAME]
    assert sorted(event["table"] for event in deleted_events) == sorted(CLEANED_TABLES)
    for deleted_event in deleted_events:
        assert deleted_event["job_id"] == CLEANUP_JOB_ID
        assert deleted_event["deleted_count"] == deleted_counts[deleted_event["table"]]
    assert "job_id" not in get_contextvars(), "job_id stays bound after the job returns"


BatchFunction = Callable[[AsyncConnection, int], Awaitable[int]]


def load_delete_expired_sessions_batch() -> BatchFunction:
    """Import the sessions batch function, so its absence fails the test as an ImportError."""
    from app.repositories.user_sessions import (  # noqa: PLC0415 (missing until implemented)
        delete_expired_sessions_batch,
    )

    return delete_expired_sessions_batch


def load_delete_stale_idempotency_keys_batch() -> BatchFunction:
    """Import the idempotency keys batch function, failing as an ImportError while it is absent."""
    from app.repositories.request_idempotency_keys import (  # noqa: PLC0415 (missing until implemented)
        delete_stale_idempotency_keys_batch,
    )

    return delete_stale_idempotency_keys_batch


def load_delete_stale_webhook_events_batch() -> BatchFunction:
    """Import the webhook ledger batch function, failing as an ImportError while it is absent."""
    from app.repositories.billing_webhook_events import (  # noqa: PLC0415 (missing until implemented)
        delete_stale_webhook_events_batch,
    )

    return delete_stale_webhook_events_batch


@dataclass(frozen=True, slots=True)
class BatchCase:
    """One table's batch function, the seeder of its stale rows, and the query counting them."""

    case_name: str
    load_batch_function: Callable[[], BatchFunction]
    seed_stale_rows: StaleRowSeeder
    count_sql: Any


BATCH_CASES = [
    BatchCase(
        "user_sessions",
        load_delete_expired_sessions_batch,
        seed_expired_sessions,
        COUNT_SESSIONS_SQL,
    ),
    BatchCase(
        "request_idempotency_keys",
        load_delete_stale_idempotency_keys_batch,
        seed_stale_idempotency_keys,
        COUNT_IDEMPOTENCY_KEYS_SQL,
    ),
    BatchCase(
        "billing_webhook_events",
        load_delete_stale_webhook_events_batch,
        seed_stale_webhook_events,
        COUNT_WEBHOOK_EVENTS_SQL,
    ),
]


@pytest.mark.parametrize("batch_case", BATCH_CASES, ids=[case.case_name for case in BATCH_CASES])
async def test_b26_each_batch_deletes_at_most_the_batch_size_and_reports_its_count(
    database_engine: AsyncEngine, seeded_user_id: uuid.UUID, batch_case: BatchCase
) -> None:
    """B-26: one batch call deletes no more than the batch size and returns how many it deleted."""
    batch_function = batch_case.load_batch_function()
    await run_cleanup_job(database_engine)
    marker = build_marker("batch")
    async with database_engine.begin() as connection:
        await batch_case.seed_stale_rows(connection, seeded_user_id, marker, 3)

    async with database_engine.begin() as connection:
        deleted_count = await batch_function(connection, 2)

    # Exact, for the serial-suite reason given in the idempotency test above: the run beforehand
    # cleared every other stale row, so the batch can only have taken two of these three.
    assert deleted_count == 2
    assert await count_seeded_rows(database_engine, batch_case.count_sql, marker) == 1
