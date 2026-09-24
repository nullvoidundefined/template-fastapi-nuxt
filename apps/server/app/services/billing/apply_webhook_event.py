"""Applies one allowlisted Stripe event to `user_subscriptions` (spec B-51).

Five events, three handlers. `checkout.session.completed` links the customer and subscription to
the user named in the session's `metadata.user_id`, the only link Stripe carries back to our user.
The three subscription events write the status, the plan, the period, and the cancel flag onto the
row naming the subscription; when no row names it yet, because Stripe delivered the subscription
before the checkout, the subscription's own `metadata.user_id` (set at checkout) creates the row,
or fills the user's row when it names no subscription yet. A user's row that already names a
different subscription is left alone: the event is a late one for a subscription the user has
since replaced, and it is logged as `billing_subscription_event_ignored`. Stripe does not deliver
events in order, so a subscription event created before the one last applied to the row is
dropped the same way: the row stores the event's `created` time with the state it wrote.
`invoice.payment_failed` sets `past_due` on the row naming the invoice's subscription.

A payload whose fields do not validate raises, which fails the event so Stripe retries it. An event
that is well formed but names nothing we hold, such as a checkout without a user, is logged and
changes nothing: retrying it could never succeed. The same holds before either handler links a
user through `metadata.user_id`: a user id naming no user, or a customer already linked to a
different user, is logged and the event is marked processed with no change, where letting the
foreign key or the unique customer constraint raise would have Stripe retry it for three days.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.clients.stripe import StripeWebhookEvent
from app.constants.billing import StripeEventType, UserSubscriptionStatus
from app.repositories.user_subscriptions import (
    SubscriptionState,
    get_subscription_by_customer_id,
    link_subscription_to_user,
    set_subscription_status,
    update_subscription_state,
    upsert_subscription_for_user,
)
from app.repositories.users import lock_user_by_id
from app.schemas.billing import (
    StripeCheckoutSession,
    StripeInvoice,
    StripeSubscription,
    StripeSubscriptionItem,
)

USER_ID_METADATA_KEY = "user_id"

EventHandler = Callable[[AsyncConnection, StripeWebhookEvent], Awaitable[None]]

logger = structlog.get_logger(__name__)


async def apply_webhook_event(connection: AsyncConnection, event: StripeWebhookEvent) -> None:
    """Run the handler registered for the event's type on the event."""
    handler = EVENT_HANDLERS[StripeEventType(event.type)]
    await handler(connection, event)


async def apply_checkout_completed(connection: AsyncConnection, event: StripeWebhookEvent) -> None:
    """Link the session's customer and subscription to the user its metadata names."""
    session = StripeCheckoutSession.model_validate(event.data_object)
    user_id = read_metadata_user_id(session.metadata or {})
    if user_id is None or session.customer is None or session.subscription is None:
        logger.warning("billing_checkout_unlinkable", checkout_session_id=session.id)
        return
    if not await is_linkable_to_user(connection, user_id, session.customer):
        return
    is_linked = await link_subscription_to_user(
        connection, user_id, session.customer, session.subscription
    )
    if not is_linked:
        logger.info("billing_checkout_link_ignored", stripe_subscription_id=session.subscription)


async def apply_subscription_change(connection: AsyncConnection, event: StripeWebhookEvent) -> None:
    """Write the subscription's state onto its row, creating the row from metadata if needed."""
    subscription = StripeSubscription.model_validate(event.data_object)
    state = build_subscription_state(subscription, event.created)
    if await update_subscription_state(connection, subscription.id, state):
        return
    user_id = read_metadata_user_id(subscription.metadata)
    if user_id is None:
        logger.info("billing_subscription_unmatched", stripe_subscription_id=subscription.id)
        return
    if not await is_linkable_to_user(connection, user_id, subscription.customer):
        return
    if not await upsert_subscription_for_user(
        connection, user_id, subscription.customer, subscription.id, state
    ):
        logger.info(
            "billing_subscription_event_ignored",
            stripe_subscription_id=subscription.id,
            user_id=str(user_id),
        )


async def apply_payment_failed(connection: AsyncConnection, event: StripeWebhookEvent) -> None:
    """Mark the invoice's subscription past due."""
    invoice = StripeInvoice.model_validate(event.data_object)
    subscription_id = read_invoice_subscription_id(invoice)
    if subscription_id is None:
        logger.info("billing_invoice_without_subscription", stripe_invoice_id=invoice.id)
        return
    event_created_at = datetime.fromtimestamp(event.created, UTC)
    is_written = await set_subscription_status(
        connection, subscription_id, UserSubscriptionStatus.PAST_DUE, event_created_at
    )
    if not is_written:
        logger.info("billing_payment_failure_ignored", stripe_subscription_id=subscription_id)


EVENT_HANDLERS: Mapping[StripeEventType, EventHandler] = {
    StripeEventType.CHECKOUT_SESSION_COMPLETED: apply_checkout_completed,
    StripeEventType.CUSTOMER_SUBSCRIPTION_CREATED: apply_subscription_change,
    StripeEventType.CUSTOMER_SUBSCRIPTION_UPDATED: apply_subscription_change,
    StripeEventType.CUSTOMER_SUBSCRIPTION_DELETED: apply_subscription_change,
    StripeEventType.INVOICE_PAYMENT_FAILED: apply_payment_failed,
}


async def is_linkable_to_user(
    connection: AsyncConnection, user_id: uuid.UUID, customer_id: str
) -> bool:
    """Return True when the user exists and the customer is unlinked or already theirs.

    The user's row is locked until the transaction ends, so the account cannot be deleted between
    this check and the write that links it.
    """
    if await lock_user_by_id(connection, user_id) is None:
        logger.warning("billing_link_user_missing", user_id=str(user_id))
        return False
    linked_row = await get_subscription_by_customer_id(connection, customer_id)
    if linked_row is not None and linked_row.user_id != user_id:
        logger.warning(
            "billing_link_customer_owned_by_other_user",
            stripe_customer_id=customer_id,
            user_id=str(user_id),
        )
        return False
    return True


def build_subscription_state(
    subscription: StripeSubscription, event_created: int
) -> SubscriptionState:
    """Return the columns to write, reading the price and period from the first item."""
    first_item = subscription.items.data[0] if subscription.items.data else None
    period_start, period_end = read_subscription_period(subscription, first_item)
    return SubscriptionState(
        status=subscription.status,
        plan_id=first_item.price.id if first_item else None,
        current_period_start=convert_stripe_timestamp(period_start),
        current_period_end=convert_stripe_timestamp(period_end),
        is_canceling_at_period_end=subscription.cancel_at_period_end,
        last_stripe_event_created_at=datetime.fromtimestamp(event_created, UTC),
    )


def read_subscription_period(
    subscription: StripeSubscription, first_item: StripeSubscriptionItem | None
) -> tuple[int | None, int | None]:
    """Return the period from the item when the API version puts it there, else the top level."""
    if first_item is not None and first_item.current_period_start is not None:
        return first_item.current_period_start, first_item.current_period_end
    return subscription.current_period_start, subscription.current_period_end


def read_invoice_subscription_id(invoice: StripeInvoice) -> str | None:
    """Return the invoice's subscription from the current API shape, or the older top level."""
    details = invoice.parent.subscription_details if invoice.parent else None
    if details is not None and details.subscription:
        return details.subscription
    return invoice.subscription


def read_metadata_user_id(metadata: Mapping[str, str]) -> uuid.UUID | None:
    """Return the user id the metadata names, or None when it is absent or not a UUID."""
    raw_user_id = metadata.get(USER_ID_METADATA_KEY)
    if not raw_user_id:
        return None
    try:
        return uuid.UUID(raw_user_id)
    except ValueError as err:
        logger.warning("billing_metadata_user_id_invalid", exc_info=err)
        return None


def convert_stripe_timestamp(seconds: int | None) -> datetime | None:
    """Return Stripe's Unix seconds as an aware UTC datetime, or None when absent."""
    return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None
