"""B-22, B-33, and R-346 unit tests for the Stripe client in app/clients/stripe.py.

The client is the real one, its SDK talking to `httpx.MockTransport` through `StripeRecorder`, so
each assertion is about the request Stripe would really receive: the endpoint, the form fields,
the bearer key, the forwarded request ID, and the timeout. A Stripe error must raise after one
attempt, because the SDK's own retries would stretch a call past the ten-second bound.
"""

import pytest
import stripe
import structlog
from pydantic import SecretStr

from tests.conftest import STRIPE_TEST_API_KEY, UNREACHABLE_DATABASE_URL, StripeRecorder

PRICE_ID = "price_basic123"
USER_ID = "7d4f2a3e-1111-4c2b-9a7e-2f3d4c5b6a7e"
SUCCESS_URL = "https://client.example.test/dashboard?checkout=success"
CANCEL_URL = "https://client.example.test/dashboard?checkout=cancelled"
CUSTOMER_ID = "cus_unit123"
RETURN_URL = "https://client.example.test/dashboard"
STRIPE_TIMEOUT_SECONDS = 10.0
REQUEST_ID = "req-stripe-unit-1"


async def test_b33_checkout_posts_a_subscription_session_carrying_the_user_id() -> None:
    """One POST to /v1/checkout/sessions in subscription mode, answered with the session URL."""
    recorder = StripeRecorder()
    client = recorder.build_client()

    url = await client.create_checkout_session(PRICE_ID, USER_ID, SUCCESS_URL, CANCEL_URL)

    assert url == "https://checkout.stripe.test/c/pay/cs_test_1"
    [request] = recorder.requests
    assert request.method == "POST"
    assert request.url.host == "api.stripe.com"
    assert request.url.path == "/v1/checkout/sessions"
    assert request.headers["Authorization"] == f"Bearer {STRIPE_TEST_API_KEY}"
    form = recorder.read_form()
    assert form["mode"] == "subscription"
    assert form["line_items[0][price]"] == PRICE_ID
    assert form["line_items[0][quantity]"] == "1"
    assert form["metadata[user_id]"] == USER_ID
    assert form["success_url"] == SUCCESS_URL
    assert form["cancel_url"] == CANCEL_URL


async def test_b22_portal_posts_the_customer_and_the_return_url() -> None:
    """One POST to /v1/billing_portal/sessions, answered with the portal URL."""
    recorder = StripeRecorder()
    client = recorder.build_client()

    url = await client.create_portal_session(CUSTOMER_ID, RETURN_URL)

    assert url == "https://billing.stripe.test/p/session/bps_test_1"
    [request] = recorder.requests
    assert request.url.path == "/v1/billing_portal/sessions"
    assert recorder.read_form() == {"customer": CUSTOMER_ID, "return_url": RETURN_URL}


async def test_r346_every_stripe_call_carries_a_ten_second_timeout_and_the_request_id() -> None:
    """httpx is told a finite timeout for every phase, and the bound request ID is forwarded."""
    recorder = StripeRecorder()
    client = recorder.build_client()
    structlog.contextvars.bind_contextvars(request_id=REQUEST_ID)
    try:
        await client.create_portal_session(CUSTOMER_ID, RETURN_URL)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")

    [request] = recorder.requests
    assert request.extensions["timeout"] == {
        "connect": STRIPE_TIMEOUT_SECONDS,
        "read": STRIPE_TIMEOUT_SECONDS,
        "write": STRIPE_TIMEOUT_SECONDS,
        "pool": STRIPE_TIMEOUT_SECONDS,
    }
    assert request.headers["X-Request-Id"] == REQUEST_ID


async def test_the_api_base_points_the_client_at_stripe_mock() -> None:
    """A configured API base, as the e2e stack sets for stripe-mock, replaces api.stripe.com."""
    recorder = StripeRecorder()
    client = recorder.build_client(api_base="http://stripe-mock:12111")

    await client.create_portal_session(CUSTOMER_ID, RETURN_URL)

    [request] = recorder.requests
    assert request.url.scheme == "http"
    assert request.url.host == "stripe-mock"
    assert request.url.port == 12111


async def test_a_stripe_error_raises_after_exactly_one_attempt() -> None:
    """A 500 from Stripe raises its error and is not retried, so the call stays inside its bound."""
    recorder = StripeRecorder(failure_status=500)
    client = recorder.build_client()

    with pytest.raises(stripe.StripeError):
        await client.create_checkout_session(PRICE_ID, USER_ID, SUCCESS_URL, CANCEL_URL)

    assert len(recorder.requests) == 1


def test_the_factory_builds_no_client_without_a_secret_key_and_one_with_it() -> None:
    """Billing without STRIPE_SECRET_KEY has no client; with the key it has the real one."""
    from app.clients.stripe import (  # noqa: PLC0415
        StripeBillingClient,
        create_stripe_billing_client,
    )
    from app.core.settings import Settings  # noqa: PLC0415

    unconfigured = Settings(
        database_url=SecretStr(UNREACHABLE_DATABASE_URL), stripe_secret_key=None
    )
    configured = Settings(
        database_url=SecretStr(UNREACHABLE_DATABASE_URL),
        stripe_secret_key=SecretStr(STRIPE_TEST_API_KEY),
    )

    assert create_stripe_billing_client(unconfigured) is None
    assert isinstance(create_stripe_billing_client(configured), StripeBillingClient)
