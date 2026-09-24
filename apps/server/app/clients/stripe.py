"""Creates Stripe Checkout and billing portal sessions through the `stripe` SDK, instrumented.

A thin client over the two Stripe calls the API makes. The SDK talks through its own async httpx
client, configured here with a ten-second timeout and no automatic retries: the telemetry wrapper
bounds each whole call with the same ten seconds, and a retry inside the SDK would spend that
bound on a second attempt the caller never asked for. Checkout is made safe to retry by the
`Idempotency-Key` middleware in front of the route instead.

Every call runs inside `with_client_telemetry`, so it is logged with its duration and outcome and
carries the request ID to Stripe as `X-Request-Id` (R-346). A Stripe error raises; the route turns
it into a 500 and the idempotency claim is released so the client's retry runs again.

No client is built without `STRIPE_SECRET_KEY`: `create_stripe_billing_client` returns None and
the billing routes answer 503 `BILLING_NOT_CONFIGURED`.

`construct_webhook_event` is the SDK's signature check for webhook deliveries. It makes no network
call and needs no API key, only the endpoint's signing secret, so it is a function rather than a
method of the client.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import stripe
import structlog
from pydantic import SecretStr
from stripe.params.checkout import SessionCreateParams as CheckoutSessionCreateParams

from app.clients.telemetry import with_client_telemetry
from app.core.settings import Settings

STRIPE_PROVIDER = "stripe"
CREATE_CHECKOUT_SESSION_OPERATION = "create_checkout_session"
CREATE_PORTAL_SESSION_OPERATION = "create_portal_session"
STRIPE_TIMEOUT_SECONDS = 10.0
STRIPE_MAX_NETWORK_RETRIES = 0
SUBSCRIPTION_MODE = "subscription"
SUBSCRIPTION_QUANTITY = 1
MISSING_URL_MESSAGE = "Stripe answered a session without a URL"
# Stripe's own default: a signature older than five minutes is refused as a possible replay.
WEBHOOK_TOLERANCE_SECONDS = 300

logger = structlog.get_logger(__name__)


class StripeBillingClient:
    """Creates the two hosted Stripe pages a signed-in user is redirected to."""

    def __init__(
        self,
        secret_key: SecretStr,
        api_base: str | None = None,
        http_client: stripe.HTTPXClient | None = None,
    ) -> None:
        """Build the SDK client on an async httpx transport with the timeout and no retries."""
        self.http_client = http_client or build_stripe_http_client()
        self.sdk_client = stripe.StripeClient(
            secret_key.get_secret_value(),
            base_addresses={"api": api_base} if api_base else {},
            http_client=self.http_client,
            max_network_retries=STRIPE_MAX_NETWORK_RETRIES,
        )

    async def create_checkout_session(
        self, price_id: str, user_id: str, success_url: str, cancel_url: str
    ) -> str:
        """Create a subscription Checkout session for one price and user; return its URL.

        `metadata.user_id` is the only link the webhook has from the completed session back to
        the user, and the same value rides on the subscription so its own events carry it too.
        """
        params: CheckoutSessionCreateParams = {
            "mode": SUBSCRIPTION_MODE,
            "line_items": [{"price": price_id, "quantity": SUBSCRIPTION_QUANTITY}],
            "metadata": {"user_id": user_id},
            "subscription_data": {"metadata": {"user_id": user_id}},
            "client_reference_id": user_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

        async def create_session(forwarded_headers: Mapping[str, str]) -> str | None:
            session = await self.sdk_client.v1.checkout.sessions.create_async(
                params, {"headers": forwarded_headers}
            )
            return session.url

        url = await with_client_telemetry(
            STRIPE_PROVIDER,
            CREATE_CHECKOUT_SESSION_OPERATION,
            create_session,
            STRIPE_TIMEOUT_SECONDS,
        )
        return require_session_url(url)

    async def create_portal_session(self, customer_id: str, return_url: str) -> str:
        """Create a billing portal session for one Stripe customer; return its URL."""

        async def create_session(forwarded_headers: Mapping[str, str]) -> str:
            session = await self.sdk_client.v1.billing_portal.sessions.create_async(
                {"customer": customer_id, "return_url": return_url},
                {"headers": forwarded_headers},
            )
            return session.url

        url = await with_client_telemetry(
            STRIPE_PROVIDER,
            CREATE_PORTAL_SESSION_OPERATION,
            create_session,
            STRIPE_TIMEOUT_SECONDS,
        )
        return require_session_url(url)

    async def close(self) -> None:
        """Close the SDK's connection pool when the application shuts down."""
        # The SDK leaves this one method unannotated, although it only awaits httpx's aclose().
        await self.http_client.close_async()  # type: ignore[no-untyped-call]


def build_stripe_http_client() -> stripe.HTTPXClient:
    """Return the SDK's async httpx transport with the ten-second timeout on every request."""
    return stripe.HTTPXClient(timeout=STRIPE_TIMEOUT_SECONDS)


def create_stripe_billing_client(settings: Settings) -> StripeBillingClient | None:
    """Return the client when STRIPE_SECRET_KEY is set, and None when billing is not configured."""
    if settings.stripe_secret_key is None:
        return None
    return StripeBillingClient(settings.stripe_secret_key, api_base=settings.stripe_api_base)


def require_session_url(url: str | None) -> str:
    """Return the session URL, raising when Stripe answered a session without one."""
    if not url:
        raise ValueError(MISSING_URL_MESSAGE)
    return url


@dataclass(slots=True, frozen=True)
class StripeWebhookEvent:
    """One verified Stripe event: its id, its type, and the object it is about, as plain JSON."""

    id: str
    type: str
    data_object: dict[str, Any]


class InvalidWebhookSignatureError(Exception):
    """The delivery's signature did not verify, or what it signed is not a Stripe event."""


def construct_webhook_event(
    payload: bytes, signature_header: str, signing_secret: SecretStr
) -> StripeWebhookEvent:
    """Verify the Stripe-Signature over the raw bytes, then read the event they carry.

    The SDK checks the HMAC-SHA256 of `<timestamp>.<payload>` under the signing secret and that
    the timestamp is inside its five-minute tolerance, so a captured delivery cannot be replayed
    later. Only bytes that verified are parsed. Anything that fails either step raises
    `InvalidWebhookSignatureError`, because a payload that is not a Stripe event was not sent by
    Stripe whatever its signature says.
    """
    try:
        stripe.WebhookSignature.verify_header(
            payload.decode("utf-8"),
            signature_header,
            signing_secret.get_secret_value(),
            WEBHOOK_TOLERANCE_SECONDS,
        )
        event = json.loads(payload)
        return StripeWebhookEvent(
            id=str(event["id"]), type=str(event["type"]), data_object=dict(event["data"]["object"])
        )
    except (stripe.SignatureVerificationError, ValueError, LookupError, TypeError) as err:
        logger.warning("stripe_webhook_signature_rejected", exc_info=err)
        raise InvalidWebhookSignatureError from err
