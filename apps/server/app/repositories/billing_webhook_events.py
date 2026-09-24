"""Data access for billing_webhook_events: claim a delivery, then mark it processed or failed.

The claim is the spec's single conditional upsert. A first delivery inserts a `claimed` row; a
redelivery takes the row back only when its last attempt failed or its claim is more than ten
minutes old, the mark a crashed handler leaves. When the upsert takes nothing, the row is read in
the same transaction to tell a processed event, which the caller acknowledges, from one another
delivery claimed moments ago, which the caller refuses so Stripe delivers it again. Every
comparison uses Postgres's `now()`, so the application's clock never enters into it.

`delete_stale_webhook_events_batch` is the hourly cleanup job's statement for this table: it
deletes at most one batch of ledger rows last attempted more than thirty days ago, found through
the `attempted_at` index, and skips any row a webhook delivery holds locked. The batch is a
materialized CTE, because a LIMIT subquery may run more than once per DELETE and so delete more
than one batch.
"""

from datetime import timedelta

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

from app.constants.billing import (
    STALE_CLAIM_MINUTES,
    BillingWebhookEventStatus,
    WebhookClaimOutcome,
)
from app.constants.cleanup import WEBHOOK_EVENT_RETENTION
from app.db.tables import billing_webhook_events

STALE_CLAIM_AGE = timedelta(minutes=STALE_CLAIM_MINUTES)
events = billing_webhook_events


async def claim_webhook_event(
    connection: AsyncConnection, stripe_event_id: str, event_type: str
) -> WebhookClaimOutcome:
    """Claim the event for this delivery, or report whether it is processed or held elsewhere."""
    insert_statement = insert(events).values(
        stripe_event_id=stripe_event_id,
        event_type=event_type,
        status=BillingWebhookEventStatus.CLAIMED.value,
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=[events.c.stripe_event_id],
        set_={"status": BillingWebhookEventStatus.CLAIMED.value, "attempted_at": func.now()},
        where=or_(
            events.c.status == BillingWebhookEventStatus.FAILED.value,
            and_(
                events.c.status == BillingWebhookEventStatus.CLAIMED.value,
                events.c.attempted_at < func.now() - STALE_CLAIM_AGE,
            ),
        ),
    ).returning(events.c.id)
    if (await connection.execute(statement)).first() is not None:
        return WebhookClaimOutcome.CLAIMED
    return await read_unclaimable_outcome(connection, stripe_event_id)


async def read_unclaimable_outcome(
    connection: AsyncConnection, stripe_event_id: str
) -> WebhookClaimOutcome:
    """Return why the claim took nothing: the event is processed, or a live claim holds it."""
    statement = select(events.c.status).where(events.c.stripe_event_id == stripe_event_id)
    status = (await connection.execute(statement)).scalar_one()
    if status == BillingWebhookEventStatus.PROCESSED.value:
        return WebhookClaimOutcome.ALREADY_PROCESSED
    return WebhookClaimOutcome.IN_PROGRESS


async def mark_webhook_event_processed(connection: AsyncConnection, stripe_event_id: str) -> None:
    """Record that the event's changes were applied, in the transaction that applied them."""
    statement = (
        update(events)
        .where(events.c.stripe_event_id == stripe_event_id)
        .values(status=BillingWebhookEventStatus.PROCESSED.value, processed_at=func.now())
    )
    await connection.execute(statement)


async def mark_webhook_event_failed(connection: AsyncConnection, stripe_event_id: str) -> None:
    """Record that the handler failed, so Stripe's redelivery claims the event again."""
    statement = (
        update(events)
        .where(
            events.c.stripe_event_id == stripe_event_id,
            events.c.status == BillingWebhookEventStatus.CLAIMED.value,
        )
        .values(status=BillingWebhookEventStatus.FAILED.value)
    )
    await connection.execute(statement)


async def delete_stale_webhook_events_batch(connection: AsyncConnection, batch_size: int) -> int:
    """Delete up to `batch_size` ledger rows past their retention and return how many went."""
    stale_batch = (
        select(events.c.id)
        .where(events.c.attempted_at < func.now() - WEBHOOK_EVENT_RETENTION)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("stale_batch")
        .prefix_with("MATERIALIZED")
    )
    result = await connection.execute(delete(events).where(events.c.id == stale_batch.c.id))
    return result.rowcount
