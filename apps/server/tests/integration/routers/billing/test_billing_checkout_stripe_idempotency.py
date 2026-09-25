"""IAN-373: a keyed checkout sends Stripe one idempotency key per claim generation.

The `Idempotency-Key` middleware stores the response only after the handler returns, so a process
that dies after Stripe created the Checkout session but before the claim completed leaves the row
in progress. Once its lease lapses, the client's retry takes the claim over and runs the handler
again. Without a Stripe idempotency key that second run creates a second session; with one, Stripe
answers the first session again.

The key must not simply follow the client's key, though. Stripe saves the first result for a key
for 24 hours, a 500 included, so a claim released after a failed Stripe call must reach Stripe
under a new key or the retry B-18 promises would replay the failure. A takeover keeps the claim
row, while a release deletes it and the retry inserts a new one, so the row is the generation.

The crash is reproduced by what it leaves behind: a completed claim is put back in progress with
an expired lease and its stored response cleared, which is the row a holder that died after the
Stripe call would have left.
"""

import re
import uuid

import httpx
import pytest
from sqlalchemy import text

from tests.conftest import StripeRecorder
from tests.integration.routers.billing.conftest import BillingDatabase
from tests.integration.routers.conftest import CookieTools, EmailFactory

CHECKOUT_PATH = "/v1/billing/checkout"
PRICE_ID = "price_Basic123"
STRIPE_IDEMPOTENCY_HEADER = "idempotency-key"
# The SDK sends a random key of its own when the caller passes none, so a derived key is told
# apart by its shape: the checkout prefix and a SHA-256 hex digest.
DERIVED_CHECKOUT_KEY_PATTERN = re.compile(r"checkout-[0-9a-f]{64}")
REVERT_TO_CRASHED_CLAIM_SQL = text(
    "UPDATE request_idempotency_keys SET state = 'in_progress', "
    "locked_until = now() - interval '1 second', status_code = NULL, response_body = NULL, "
    "response_body_bytes = NULL, response_content_type = NULL, response_headers = NULL "
    "WHERE key = :key AND user_id = :user_id"
)


def is_derived_checkout_key(stripe_key: str | None) -> bool:
    """Return True when the key is one the checkout derived, not the SDK's random default."""
    return stripe_key is not None and DERIVED_CHECKOUT_KEY_PATTERN.fullmatch(stripe_key) is not None


def read_stripe_idempotency_keys(stripe_recorder: StripeRecorder) -> list[str | None]:
    """Return the idempotency key each recorded Stripe request carried, in order."""
    return [request.headers.get(STRIPE_IDEMPOTENCY_HEADER) for request in stripe_recorder.requests]


@pytest.mark.integration
async def test_ian373_a_takeover_after_a_crash_reaches_stripe_under_the_same_key(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """The retry that takes over a crashed claim must reach Stripe under the first call's key."""
    user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("crash"))
    client_key = f"crash-{uuid.uuid4()}"
    headers = {**cookies.header(raw_token), "Idempotency-Key": client_key}

    first = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers)
    async with billing_db.auth_db.engine.begin() as connection:
        reverted = await connection.execute(
            REVERT_TO_CRASHED_CLAIM_SQL, {"key": client_key, "user_id": user_id}
        )
    retried = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers
    )

    assert first.status_code == 200, first.text
    assert reverted.rowcount == 1
    assert retried.status_code == 200, retried.text
    stripe_keys = read_stripe_idempotency_keys(stripe_recorder)
    assert len(stripe_keys) == 2, stripe_keys
    assert all(is_derived_checkout_key(stripe_key) for stripe_key in stripe_keys), stripe_keys
    assert stripe_keys[1] == stripe_keys[0]


@pytest.mark.integration
async def test_ian373_a_retry_after_a_released_failure_reaches_stripe_under_a_new_key(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """A released claim must not reuse the key Stripe saved the failure under."""
    _user_id, raw_token = await billing_db.seed_signed_in_user(auth_emails("released"))
    headers = {**cookies.header(raw_token), "Idempotency-Key": f"released-{uuid.uuid4()}"}
    stripe_recorder.failure_status = 500

    failed = await billing_browser.post(CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers)
    stripe_recorder.failure_status = None
    retried = await billing_browser.post(
        CHECKOUT_PATH, json={"price_id": PRICE_ID}, headers=headers
    )

    assert failed.status_code == 500, failed.text
    assert retried.status_code == 200, retried.text
    stripe_keys = read_stripe_idempotency_keys(stripe_recorder)
    assert len(stripe_keys) == 2, stripe_keys
    assert all(is_derived_checkout_key(stripe_key) for stripe_key in stripe_keys), stripe_keys
    assert stripe_keys[0] != stripe_keys[1]


@pytest.mark.integration
async def test_ian373_two_users_sending_the_same_client_key_reach_stripe_under_different_keys(
    billing_browser: httpx.AsyncClient,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    cookies: CookieTools,
    stripe_recorder: StripeRecorder,
) -> None:
    """A client key is scoped to its user, so Stripe must never see one user's key reused."""
    _first_id, first_token = await billing_db.seed_signed_in_user(auth_emails("shared-a"))
    _second_id, second_token = await billing_db.seed_signed_in_user(auth_emails("shared-b"))
    shared_key = f"shared-{uuid.uuid4()}"

    for raw_token in (first_token, second_token):
        response = await billing_browser.post(
            CHECKOUT_PATH,
            json={"price_id": PRICE_ID},
            headers={**cookies.header(raw_token), "Idempotency-Key": shared_key},
        )
        assert response.status_code == 200, response.text

    stripe_keys = read_stripe_idempotency_keys(stripe_recorder)
    assert len(stripe_keys) == 2, stripe_keys
    assert all(is_derived_checkout_key(stripe_key) for stripe_key in stripe_keys), stripe_keys
    assert stripe_keys[0] != stripe_keys[1]
