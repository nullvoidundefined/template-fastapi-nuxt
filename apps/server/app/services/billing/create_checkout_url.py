"""Creates the Stripe Checkout session a signed-in user subscribes through, and returns its URL.

Stripe sends the browser back to the dashboard either way, with the outcome in the query string,
so the page can say whether the checkout went through. Both URLs are built from `client_url`, the
web origin, because the browser returns to the web client rather than to the API.

A keyed request reaches Stripe under an idempotency key derived from its claim generation
(IAN-373), so a retry that takes over a claim whose holder died after Stripe answered gets the
same session back instead of a second one, while a retry after a released failure is a new call.
"""

import uuid

from app.clients.stripe import StripeBillingClient

DASHBOARD_PATH = "/dashboard"
CHECKOUT_SUCCESS_QUERY = "checkout=success"
CHECKOUT_CANCELLED_QUERY = "checkout=cancelled"
CHECKOUT_IDEMPOTENCY_KEY_PREFIX = "checkout-"


async def create_checkout_url(
    stripe_client: StripeBillingClient,
    client_url: str,
    user_id: uuid.UUID,
    price_id: str,
    claim_generation: str | None = None,
) -> str:
    """Create a subscription Checkout session for the user and price; return the Stripe URL."""
    dashboard_url = build_dashboard_url(client_url)
    return await stripe_client.create_checkout_session(
        price_id,
        str(user_id),
        f"{dashboard_url}?{CHECKOUT_SUCCESS_QUERY}",
        f"{dashboard_url}?{CHECKOUT_CANCELLED_QUERY}",
        build_checkout_idempotency_key(claim_generation),
    )


def build_checkout_idempotency_key(claim_generation: str | None) -> str | None:
    """Return Stripe's idempotency key for this claim generation, or None for an unkeyed call."""
    if claim_generation is None:
        return None
    return f"{CHECKOUT_IDEMPOTENCY_KEY_PREFIX}{claim_generation}"


def build_dashboard_url(client_url: str) -> str:
    """Return the dashboard's absolute URL, tolerating a trailing slash on the origin."""
    return f"{client_url.rstrip('/')}{DASHBOARD_PATH}"
