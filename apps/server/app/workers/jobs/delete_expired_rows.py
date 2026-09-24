"""The hourly cleanup job: delete expired sessions, stale idempotency keys, and old ledger rows.

arq runs it at minute 0 of every hour (B-26). For each table it calls that table's repository
batch function, each call in its own short transaction, until a batch deletes fewer rows than the
batch size, so a large backlog never holds its locks for long and a request touching one of these
tables waits on at most one batch. A batch that skips rows another transaction holds locked
leaves them for the next hour. While the worker is down, rows accumulate until it returns, and
nothing else is affected.

It logs one `expired_rows_deleted` line per table with the count, and like every job it binds its
arq job ID into the log context for the length of the run (R-341). It returns the counts by table,
which arq stores as the job's result.
"""

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.constants.cleanup import CLEANUP_BATCH_SIZE
from app.db.tables import billing_webhook_events, request_idempotency_keys, user_sessions
from app.repositories.billing_webhook_events import delete_stale_webhook_events_batch
from app.repositories.request_idempotency_keys import delete_stale_idempotency_keys_batch
from app.repositories.user_sessions import delete_expired_sessions_batch
from app.workers.context import WorkerContext
from app.workers.report_job_failure import report_job_failure

logger = structlog.get_logger(__name__)

BatchDeleter = Callable[[AsyncConnection, int], Awaitable[int]]

TABLE_BATCH_DELETERS: tuple[tuple[str, BatchDeleter], ...] = (
    (user_sessions.name, delete_expired_sessions_batch),
    (request_idempotency_keys.name, delete_stale_idempotency_keys_batch),
    (billing_webhook_events.name, delete_stale_webhook_events_batch),
)


@report_job_failure
async def delete_expired_rows(ctx: WorkerContext) -> dict[str, int]:
    """Clear each table's expired rows in batches, log each table's count, and return the counts."""
    deleted_counts: dict[str, int] = {}
    with structlog.contextvars.bound_contextvars(job_id=ctx.get("job_id")):
        for table_name, delete_batch in TABLE_BATCH_DELETERS:
            deleted_count = await delete_in_batches(ctx["engine"], delete_batch)
            logger.info("expired_rows_deleted", table=table_name, deleted_count=deleted_count)
            deleted_counts[table_name] = deleted_count
    return deleted_counts


async def delete_in_batches(engine: AsyncEngine, delete_batch: BatchDeleter) -> int:
    """Run one batch per transaction until a batch comes back short, and return the total."""
    total_deleted_count = 0
    while True:
        async with engine.begin() as connection:
            batch_deleted_count = await delete_batch(connection, CLEANUP_BATCH_SIZE)
        total_deleted_count += batch_deleted_count
        if batch_deleted_count < CLEANUP_BATCH_SIZE:
            return total_deleted_count
