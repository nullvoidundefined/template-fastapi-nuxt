"""Data access for billing_webhook_events: claim a delivery, then mark it processed or failed.

The claim is the spec's single conditional upsert. A first delivery inserts a `claimed` row; a
redelivery takes the row back only when its last attempt failed or its claim is more than ten
minutes old, the mark a crashed handler leaves. A processed event, or one another delivery
claimed moments ago, returns nothing, and the caller acknowledges without applying it again.
Every comparison uses Postgres's `now()`, so the application's clock never enters into it.
"""

from datetime import timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

from app.constants.billing import STALE_CLAIM_MINUTES, BillingWebhookEventStatus
from app.db.tables import billing_webhook_events

STALE_CLAIM_AGE = timedelta(minutes=STALE_CLAIM_MINUTES)
events = billing_webhook_events


async def claim_webhook_event(
    connection: AsyncConnection, stripe_event_id: str, event_type: str
) -> bool:
    """Claim the event for this delivery; True when this delivery should apply it."""
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
    return (await connection.execute(statement)).first() is not None


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
