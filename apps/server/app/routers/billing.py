"""The billing routes: start a Checkout, open the portal, and receive Stripe's webhook.

Checkout and portal each take the signed-in user, call one service, and answer the hosted Stripe
URL the browser is sent to. Checkout is where a double click would cost money, so the client sends
an `Idempotency-Key` and the slice 05 middleware replays the first answer to any repeat of it.
"""

import structlog
from fastapi import APIRouter

from app.dependencies.current_user import CurrentUser, RequestConnection
from app.dependencies.settings import RequestSettings
from app.dependencies.stripe_billing_client import RequestStripeBillingClient
from app.schemas.billing import BillingRedirectData, BillingRedirectResponse, CheckoutCreate
from app.services.billing.create_checkout_url import create_checkout_url
from app.services.billing.create_portal_url import create_portal_url

router = APIRouter(prefix="/v1/billing", tags=["billing"])
logger = structlog.get_logger(__name__)


@router.post("/checkout", response_model=BillingRedirectResponse)
async def create_checkout(
    body: CheckoutCreate,
    current: CurrentUser,
    stripe_client: RequestStripeBillingClient,
    settings: RequestSettings,
) -> BillingRedirectResponse:
    """Create a subscription Checkout session for the signed-in user; answer its URL."""
    url = await create_checkout_url(
        stripe_client, settings.client_url, current.user.id, body.price_id
    )
    logger.info("billing_checkout_created", user_id=str(current.user.id))
    return BillingRedirectResponse(data=BillingRedirectData(url=url))


@router.post("/portal", response_model=BillingRedirectResponse)
async def create_portal(
    connection: RequestConnection,
    current: CurrentUser,
    stripe_client: RequestStripeBillingClient,
    settings: RequestSettings,
) -> BillingRedirectResponse:
    """Open the billing portal for the signed-in user's Stripe customer; answer its URL."""
    url = await create_portal_url(connection, stripe_client, settings.client_url, current.user.id)
    logger.info("billing_portal_created", user_id=str(current.user.id))
    return BillingRedirectResponse(data=BillingRedirectData(url=url))
