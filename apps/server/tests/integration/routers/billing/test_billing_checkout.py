"""B-33 and R-406: `POST /v1/billing/checkout` through the real application.

The signed-in user receives the Stripe Checkout URL, and the Stripe request carries subscription
mode, the price, `metadata.user_id`, and the success and cancel URLs built from `CLIENT_URL`. The
same request repeated with the same `Idempotency-Key` answers the same URL while Stripe saw one
request, which is the slice 05 middleware replaying the stored response through a real route. A
`price_id` outside `^price_[A-Za-z0-9]+$` answers 400 before any Stripe call, and so does every
malformed body. Without a session the route answers 401, and without Stripe configured 503.
"""

import uuid

import httpx
import pytest

from tests.conftest import StripeRecorder
from tests.integration.routers.billing.conftest import CLIENT_URL, BillingDatabase
from tests.integration.routers.conftest import CookieTools, EmailFactory

CHECKOUT_PATH = "/v1/billing/checkout"
PRICE_ID = "price_Basic123"


@pytest.mark.integration
async def test_b33_checkout_answers_the_session_url_and_a_keyed_repeat_replays_it(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """One Stripe request in subscription mode for this user; the repeat replays the same URL."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("checkout"))
    headers = {**cookies.header(raw_token), "Idempotency-Key": f"checkout-{uuid.uuid4()}"}

    first = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers)
    repeat = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers)

    assert first.status_code == 200, first.text
    assert first.json() == {"data": {"url": "https://checkout.stripe.test/c/pay/cs_test_1"}}
    assert repeat.status_code == 200, repeat.text
    assert repeat.json() == first.json()
    assert len(stripe_recorder.requests) == 1
    assert stripe_recorder.requests[0].url.path == "/v1/checkout/sessions"
    form = stripe_recorder.read_form()
    assert form["mode"] == "subscription"
    assert form["line_items[0][price]"] == PRICE_ID
    assert form["metadata[user_id]"] == str(user_id)
    assert form["success_url"] == f"{CLIENT_URL}/dashboard?checkout=success"
    assert form["cancel_url"] == f"{CLIENT_URL}/dashboard?checkout=cancelled"


@pytest.mark.integration
async def test_b33_a_checkout_without_a_key_creates_a_session_each_time(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """Without an Idempotency-Key nothing is replayed, so the replay above is the key's doing."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("unkeyed"))

    first = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=cookies.header(raw_token)
    )
    second = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=cookies.header(raw_token)
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["url"] != second.json()["data"]["url"]
    assert len(stripe_recorder.requests) == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        {"price_id": "prod_Basic123"},
        {"price_id": "price_"},
        {"price_id": "price_basic-123"},
        {"price_id": "price_basic 123"},
        {"price_id": "price_1' OR '1'='1"},
        {"price_id": "price_" + "a" * 300},
        {"price_id": "price_café"},
        {"price_id": 123},
        {},
        {"price_id": PRICE_ID, "quantity": 5},
    ],
)
async def test_b33_an_invalid_price_id_answers_400_without_calling_stripe(  # noqa: PLR0913, PLR0917
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
    body: dict[str, object],
) -> None:
    """Every body outside the schema is refused with the envelope before Stripe is reached."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("invalid"))

    response = await billing_browser.post(
        CHECKOUT_PATH, json=body, headers=cookies.header(raw_token)
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_r406_a_malformed_body_answers_400_without_calling_stripe(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """Bytes that are not UTF-8 JSON are refused with the envelope, and Stripe is never called."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("malformed"))

    response = await billing_browser.post(
        CHECKOUT_PATH,
        content=b'{"price_id": "\xff\xfe"}',
        headers={**cookies.header(raw_token), "Content-Type": "application/json"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_checkout_without_a_session_answers_auth_required(
    billing_browser: httpx.AsyncClient, stripe_recorder: StripeRecorder
) -> None:
    """An anonymous checkout is refused with 401 and never reaches Stripe."""
    response = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID})

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert stripe_recorder.requests == []


@pytest.mark.integration
async def test_checkout_without_stripe_configured_answers_billing_not_configured(
    unconfigured_billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
) -> None:
    """With no STRIPE_SECRET_KEY the route answers 503 with its own code, not a bare 500."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("unconfigured"))

    response = await unconfigured_billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=cookies.header(raw_token)
    )

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "BILLING_NOT_CONFIGURED"


@pytest.mark.integration
async def test_a_stripe_failure_answers_500_and_releases_the_key_for_the_retry(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """A failed Stripe call answers 500, and the same key then succeeds once Stripe recovers."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("stripe-down"))
    headers = {**cookies.header(raw_token), "Idempotency-Key": f"retry-{uuid.uuid4()}"}
    stripe_recorder.failure_status = 500

    failed = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers)
    stripe_recorder.failure_status = None
    retried = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers
    )

    assert failed.status_code == 500, failed.text
    assert failed.json()["code"] == "SERVER_INTERNAL_ERROR"
    assert retried.status_code == 200, retried.text
    assert retried.json() == {"data": {"url": "https://checkout.stripe.test/c/pay/cs_test_2"}}
