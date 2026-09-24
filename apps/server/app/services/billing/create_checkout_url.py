"""Creates the Stripe Checkout session a signed-in user subscribes through, and returns its URL.

Stripe sends the browser back to the dashboard either way, with the outcome in the query string,
so the page can say whether the checkout went through. Both URLs are built from `client_url`, the
web origin, because the browser returns to the web client rather than to the API.
"""

import uuid

from app.clients.stripe import StripeBillingClient

DASHBOARD_PATH = "/dashboard"
CHECKOUT_SUCCESS_QUERY = "checkout=success"
CHECKOUT_CANCELLED_QUERY = "checkout=cancelled"


async def create_checkout_url(
    stripe_client: StripeBillingClient, client_url: str, user_id: uuid.UUID, price_id: str
) -> str:
    """Create a subscription Checkout session for the user and price; return the Stripe URL."""
    dashboard_url = build_dashboard_url(client_url)
    return await stripe_client.create_checkout_session(
        price_id,
        str(user_id),
        f"{dashboard_url}?{CHECKOUT_SUCCESS_QUERY}",
        f"{dashboard_url}?{CHECKOUT_CANCELLED_QUERY}",
    )


def build_dashboard_url(client_url: str) -> str:
    """Return the dashboard's absolute URL, tolerating a trailing slash on the origin."""
    return f"{client_url.rstrip('/')}{DASHBOARD_PATH}"
