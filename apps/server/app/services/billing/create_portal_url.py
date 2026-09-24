"""Opens the Stripe billing portal for the signed-in user's customer, and returns its URL.

The customer is the one the webhook recorded on the user's subscription row. A user with no row,
or a row Stripe has not yet named a customer for, has nothing the portal could show, so the
request is refused with 400 `BILLING_NO_ACCOUNT` before Stripe is called.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from app.clients.stripe import StripeBillingClient
from app.constants.error_codes import ErrorCode
from app.errors import AppError
from app.repositories.user_subscriptions import get_subscription_by_user_id
from app.services.billing.create_checkout_url import build_dashboard_url

NO_ACCOUNT_MESSAGE = "No billing account exists for this user"


class BillingNoAccountError(AppError):
    """The user has no Stripe customer, so there is no portal to open."""

    def __init__(self) -> None:
        """Answer 400 with the registry's no-account code."""
        super().__init__(400, ErrorCode.BILLING_NO_ACCOUNT, NO_ACCOUNT_MESSAGE)


async def create_portal_url(
    connection: AsyncConnection,
    stripe_client: StripeBillingClient,
    client_url: str,
    user_id: uuid.UUID,
) -> str:
    """Open a portal session for the user's customer, returning to the dashboard; answer its URL."""
    subscription = await get_subscription_by_user_id(connection, user_id)
    if subscription is None or subscription.stripe_customer_id is None:
        raise BillingNoAccountError
    return await stripe_client.create_portal_session(
        subscription.stripe_customer_id, build_dashboard_url(client_url)
    )
