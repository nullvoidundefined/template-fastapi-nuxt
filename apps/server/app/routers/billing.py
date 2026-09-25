"""The billing routes: start a Checkout, open the portal, and receive Stripe's webhook.

Checkout and portal each take the signed-in user, call one service, and answer the hosted Stripe
URL the browser is sent to. Checkout is where a double click would cost money, so the client sends
an `Idempotency-Key` and the slice 05 middleware replays the first answer to any repeat of it.

The webhook takes no user at all. It is exempt from the CSRF guard and the rate limiter by exact
path (`app/constants/exempt_paths.py`), verifies Stripe's signature over the raw body, and hands
the verified event to the ledger-backed service that applies each event at most once.
"""

import structlog
from fastapi import APIRouter, Request

from app.constants.billing import STRIPE_SIGNATURE_HEADER
from app.dependencies.current_user import CurrentUser, RequestConnection
from app.dependencies.database_engine import RequestEngine
from app.dependencies.idempotency_claim_generation import IdempotencyClaimGeneration
from app.dependencies.settings import RequestSettings
from app.dependencies.stripe_billing_client import RequestStripeBillingClient
from app.schemas.billing import (
    BillingRedirectData,
    BillingRedirectResponse,
    CheckoutCreate,
    WebhookReceivedData,
    WebhookReceivedResponse,
)
from app.schemas.errors import ErrorResponse
from app.services.billing.create_checkout_url import create_checkout_url
from app.services.billing.create_portal_url import create_portal_url
from app.services.billing.process_webhook_event import process_webhook_event
from app.services.billing.verify_webhook_event import verify_webhook_event

router = APIRouter(prefix="/v1/billing", tags=["billing"])
logger = structlog.get_logger(__name__)


@router.post("/checkout", response_model=BillingRedirectResponse)
async def create_checkout(
    body: CheckoutCreate,
    current: CurrentUser,
    stripe_client: RequestStripeBillingClient,
    settings: RequestSettings,
    claim_generation: IdempotencyClaimGeneration,
) -> BillingRedirectResponse:
    """Create a subscription Checkout session for the signed-in user; answer its URL."""
    url = await create_checkout_url(
        stripe_client, settings.client_url, current.user.id, body.price_id, claim_generation
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


@router.post(
    "/webhook",
    response_model=WebhookReceivedResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Another delivery is processing the event"},
        500: {"model": ErrorResponse, "description": "The event could not be processed"},
    },
)
async def receive_webhook(
    request: Request, engine: RequestEngine, settings: RequestSettings
) -> WebhookReceivedResponse:
    """Verify a Stripe delivery against its raw bytes and apply it at most once.

    The body is read as bytes and never parsed before the signature is checked, because any
    re-serialization would change the bytes Stripe signed. No session and no CSRF header are
    involved: Stripe sends neither, and the signature is what authenticates the request.
    """
    event = verify_webhook_event(
        await request.body(),
        request.headers.get(STRIPE_SIGNATURE_HEADER),
        settings.stripe_webhook_secret,
    )
    await process_webhook_event(engine, event)
    return WebhookReceivedResponse(data=WebhookReceivedData(received=True))
