"""B-22 and B-40: `POST /v1/billing/portal` through the real application.

A user with no Stripe customer, whether because no subscription row exists or because the row has
no customer yet, answers 400 `BILLING_NO_ACCOUNT` without calling Stripe. A user with one receives
the portal URL, created for that customer with a return URL of `{client_url}/dashboard`. A key
first used on checkout and then sent to the portal is refused, so it can never replay one route's
response into the other.
"""

import uuid

import httpx
import pytest

from tests.conftest import StripeRecorder
from tests.integration.routers.billing.conftest import CLIENT_URL, BillingDatabase
from tests.integration.routers.conftest import CookieTools, EmailFactory

PORTAL_PATH = "/v1/billing/portal"
CHECKOUT_PATH = "/v1/billing/checkout"
PRICE_ID = "price_Basic123"


def make_customer_id() -> str:
    """Return a unique Stripe-shaped customer id."""
    return f"cus_{uuid.uuid4().hex}"


@pytest.mark.integration
async def test_b22_a_user_without_a_subscription_row_answers_billing_no_account(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """No row at all is no account: 400 with the registry code, and Stripe is never called."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("no-row"))

    response = await billing_browser.post(PORTAL_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_NO_ACCOUNT"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_b22_a_row_without_a_customer_answers_billing_no_account(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """A row Stripe has not yet named a customer for is still no account."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("no-customer"))
    await billing_db.seed_subscription(user_id, customer_id=None)

    response = await billing_browser.post(PORTAL_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_NO_ACCOUNT"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_b22_a_user_with_a_customer_receives_the_portal_url(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """The portal session is created for this user's customer and returns to the dashboard."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("customer"))
    customer_id = make_customer_id()
    await billing_db.seed_subscription(user_id, customer_id=customer_id)

    response = await billing_browser.post(PORTAL_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"url": "https://billing.stripe.test/p/session/bps_test_1"}}
    [request] = stripe_recorder.requests
    assert request.url.path == "/v1/billing_portal/sessions"
    assert stripe_recorder.read_form() == {
        "customer": customer_id,
        "return_url": f"{CLIENT_URL}/dashboard",
    }


@pytest.mark.integration
async def test_portal_without_a_session_answers_auth_required(
    billing_browser: httpx.AsyncClient, stripe_recorder: StripeRecorder
) -> None:
    """An anonymous portal request is refused with 401 and never reaches Stripe."""
    response = await billing_browser.post(PORTAL_PATH)

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_portal_without_stripe_configured_answers_billing_not_configured(
    unconfigured_billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
) -> None:
    """With no STRIPE_SECRET_KEY the portal answers 503 with its own code."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("portal-off"))
    await billing_db.seed_subscription(user_id, customer_id=make_customer_id())

    response = await unconfigured_billing_browser.post(
        PORTAL_PATH, headers=cookies.header(raw_token)
    )

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "BILLING_NOT_CONFIGURED"


@pytest.mark.integration
async def test_b40_a_checkout_key_sent_to_the_portal_is_refused_as_reused(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """The key is bound to checkout, so the portal answers 422 and creates no portal session."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("cross-route"))
    await billing_db.seed_subscription(user_id, customer_id=make_customer_id())
    headers = {**cookies.header(raw_token), "Idempotency-Key": f"cross-{uuid.uuid4()}"}

    checkout = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers
    )
    portal = await billing_browser.post(PORTAL_PATH, headers=headers)

    assert checkout.status_code == 200, checkout.text
    assert portal.status_code == 422, portal.text
    assert portal.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert [request.url.path for request in stripe_recorder.requests] == ["/v1/checkout/sessions"]
