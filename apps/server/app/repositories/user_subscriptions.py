"""Data access for user_subscriptions: the portal's lookup and the webhook's writes.

A user's row is found by the user id for a request and by the Stripe subscription id for a
webhook, because a subscription event names the subscription rather than our user. Every write is
one statement, so a webhook's changes to a row land together or not at all.
"""

import uuid
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.tables import user_subscriptions


async def get_subscription_by_user_id(
    connection: AsyncConnection, user_id: uuid.UUID
) -> Row[Any] | None:
    """Return the user's subscription row, or None when the user has never had one."""
    statement = select(user_subscriptions).where(user_subscriptions.c.user_id == user_id)
    return (await connection.execute(statement)).one_or_none()
