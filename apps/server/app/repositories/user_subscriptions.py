"""Data access for user_subscriptions: the portal's lookup and the webhook's writes.

A user's row is found by the user id for a request and by the Stripe subscription id for a
webhook, because a subscription event names the subscription rather than our user. Every write is
one statement, so a webhook's changes to a row land together or not at all. The upserts conflict
on `user_id`, the one-row-per-user constraint, so a user who subscribes again after cancelling has
the same row pointed at the new customer and subscription by that checkout. A subscription event's
own upsert is narrower: it takes over a row only when the row names no subscription yet or names
this one, so a late event for a subscription the user has since replaced cannot repoint the row.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.constants.billing import UserSubscriptionStatus
from app.db.tables import user_subscriptions


@dataclass(slots=True, frozen=True)
class SubscriptionState:
    """The columns a Stripe subscription event writes, all of them at once."""

    status: UserSubscriptionStatus
    plan_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    is_canceling_at_period_end: bool


async def get_subscription_by_user_id(
    connection: AsyncConnection, user_id: uuid.UUID
) -> Row[Any] | None:
    """Return the user's subscription row, or None when the user has never had one."""
    statement = select(user_subscriptions).where(user_subscriptions.c.user_id == user_id)
    return (await connection.execute(statement)).one_or_none()


async def link_subscription_to_user(
    connection: AsyncConnection, user_id: uuid.UUID, customer_id: str, subscription_id: str
) -> None:
    """Create the user's row naming the customer and subscription, or repoint the existing one.

    The status is left alone: the subscription's own events carry it, and a checkout that arrives
    after them must not overwrite what they wrote.
    """
    ids = {"stripe_customer_id": customer_id, "stripe_subscription_id": subscription_id}
    statement = (
        insert(user_subscriptions)
        .values(user_id=user_id, **ids)
        .on_conflict_do_update(index_elements=[user_subscriptions.c.user_id], set_=ids)
    )
    await connection.execute(statement)


async def update_subscription_state(
    connection: AsyncConnection, subscription_id: str, state: SubscriptionState
) -> bool:
    """Write the state onto the row naming the subscription; False when no row names it."""
    statement = (
        update(user_subscriptions)
        .where(user_subscriptions.c.stripe_subscription_id == subscription_id)
        .values(**build_state_values(state))
        .returning(user_subscriptions.c.id)
    )
    return (await connection.execute(statement)).first() is not None


async def upsert_subscription_for_user(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    customer_id: str,
    subscription_id: str,
    state: SubscriptionState,
) -> bool:
    """Create the user's row, or fill one naming no other subscription; False when it names one."""
    values = {
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        **build_state_values(state),
    }
    statement = (
        insert(user_subscriptions)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[user_subscriptions.c.user_id],
            set_=values,
            where=or_(
                user_subscriptions.c.stripe_subscription_id.is_(None),
                user_subscriptions.c.stripe_subscription_id == subscription_id,
            ),
        )
        .returning(user_subscriptions.c.id)
    )
    return (await connection.execute(statement)).first() is not None


async def set_subscription_status(
    connection: AsyncConnection, subscription_id: str, status: UserSubscriptionStatus
) -> bool:
    """Set only the status of the row naming the subscription; False when no row names it."""
    statement = (
        update(user_subscriptions)
        .where(user_subscriptions.c.stripe_subscription_id == subscription_id)
        .values(status=status.value)
        .returning(user_subscriptions.c.id)
    )
    return (await connection.execute(statement)).first() is not None


def build_state_values(state: SubscriptionState) -> dict[str, Any]:
    """Return the state as column values, the status as its enum label."""
    return {**asdict(state), "status": state.status.value}
