"""Runs one verified Stripe event through the allowlist, the ledger, and its handler.

The steps, each in its own transaction on a connection of its own:

1. An event type outside the allowlist is acknowledged and nothing is written (B-34).
2. The event is claimed in `billing_webhook_events` and the claim committed, so a concurrent
   redelivery sees it. A delivery of an event already processed is acknowledged without applying
   it again (B-21). A delivery that meets another delivery's claim younger than ten minutes answers
   409 `BILLING_WEBHOOK_IN_PROGRESS`: that holder may yet crash, and a 200 here would end Stripe's
   retries and lose the event, so Stripe is left to deliver it again.
3. The handler's writes and the `processed` mark commit together, so an event is never marked
   processed without its changes, nor changed without being marked.
4. When the handler raises, that transaction rolls back, the event is marked `failed` in a
   transaction of its own, and the delivery answers 500 `BILLING_WEBHOOK_PROCESSING_FAILED`, so
   Stripe redelivers it and the claim upsert takes it back (B-41, B-42).

A process that dies between steps 2 and 4 leaves the event `claimed`; the claim upsert takes it
over once it is ten minutes old.
"""

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clients.stripe import StripeWebhookEvent
from app.constants.billing import HANDLED_STRIPE_EVENT_TYPES, WebhookClaimOutcome
from app.constants.error_codes import ErrorCode
from app.errors import AppError
from app.repositories.billing_webhook_events import (
    claim_webhook_event,
    mark_webhook_event_failed,
    mark_webhook_event_processed,
)
from app.services.billing.apply_webhook_event import apply_webhook_event

PROCESSING_FAILED_MESSAGE = "The webhook event could not be processed"
IN_PROGRESS_MESSAGE = "Another delivery of this webhook event is being processed"
# What a handler raises for a bad row or a bad payload: a database error, a failed validation
# (pydantic's `ValidationError` is a `ValueError`), or a missing or mistyped field. Anything else
# is a defect rather than an event Stripe should retry, and reaches the 500 handler unchanged.
HANDLER_FAILURE_TYPES = (SQLAlchemyError, ValueError, LookupError, TypeError)
# What marking the event failed may raise: any database error, not only a failure to connect, and
# the socket errors a lost connection surfaces as. Each is logged with its traceback and swallowed
# on purpose: the delivery already answers 500 PROCESSING_FAILED, Stripe redelivers it, and the
# claim left behind is taken over once it is stale, so raising here would only replace the
# registry's retryable code with an unhandled-error 500.
MARK_FAILED_FAILURE_TYPES = (SQLAlchemyError, OSError)

logger = structlog.get_logger(__name__)


class WebhookProcessingFailedError(AppError):
    """The event's handler raised; the event is marked failed for Stripe to redeliver."""

    def __init__(self) -> None:
        """Answer 500 with the registry's processing-failed code."""
        super().__init__(
            500, ErrorCode.BILLING_WEBHOOK_PROCESSING_FAILED, PROCESSING_FAILED_MESSAGE
        )


class WebhookInProgressError(AppError):
    """Another delivery holds a live claim on the event; Stripe retries the refused delivery."""

    def __init__(self) -> None:
        """Answer 409 with the registry's in-progress code."""
        super().__init__(409, ErrorCode.BILLING_WEBHOOK_IN_PROGRESS, IN_PROGRESS_MESSAGE)


async def process_webhook_event(engine: AsyncEngine, event: StripeWebhookEvent) -> None:
    """Ignore, skip, or apply the event, raising when its handler fails."""
    if event.type not in HANDLED_STRIPE_EVENT_TYPES:
        logger.info("billing_webhook_event_ignored", event_type=event.type)
        return
    async with engine.begin() as connection:
        claim_outcome = await claim_webhook_event(connection, event.id, event.type)
    if claim_outcome is WebhookClaimOutcome.ALREADY_PROCESSED:
        logger.info("billing_webhook_event_skipped", stripe_event_id=event.id)
        return
    if claim_outcome is WebhookClaimOutcome.IN_PROGRESS:
        logger.info("billing_webhook_event_in_progress", stripe_event_id=event.id)
        raise WebhookInProgressError
    try:
        async with engine.begin() as connection:
            await apply_webhook_event(connection, event)
            await mark_webhook_event_processed(connection, event.id)
    except HANDLER_FAILURE_TYPES as err:
        logger.error(
            "billing_webhook_event_failed",
            exc_info=err,
            stripe_event_id=event.id,
            event_type=event.type,
        )
        await mark_event_failed_safely(engine, event)
        raise WebhookProcessingFailedError from err
    logger.info("billing_webhook_event_processed", stripe_event_id=event.id, event_type=event.type)


async def mark_event_failed_safely(engine: AsyncEngine, event: StripeWebhookEvent) -> None:
    """Mark the event failed; if even that fails, the claim goes stale and is taken over later."""
    try:
        async with engine.begin() as connection:
            await mark_webhook_event_failed(connection, event.id)
    except MARK_FAILED_FAILURE_TYPES as err:
        logger.error("billing_webhook_mark_failed_failed", exc_info=err, stripe_event_id=event.id)
