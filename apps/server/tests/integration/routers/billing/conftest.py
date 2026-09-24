"""Fixtures for the billing routes: the real application with Stripe answered by a recorder.

The application is built through the same `build_auth_app` factory the auth and admin tests use,
so it is the public `create_app()` against the migrated Postgres, over HTTPS, with the CSRF header
on every request. The one substitution is the Stripe client: the route's dependency is overridden
with the real `StripeBillingClient` whose SDK talks to `StripeRecorder` over `httpx.MockTransport`,
so the tests assert the requests Stripe would really receive and never reach the network.

`CLIENT_URL` is pinned, because the success, cancel, and return URLs are built from it and B-22
and B-33 assert them exactly. Every Stripe variable is removed first, so a developer's shell
cannot configure billing behind a test's back.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import Row, text

from tests.conftest import StripeRecorder

CLIENT_URL = "https://client.example.test"
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
STRIPE_VARIABLES = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_API_BASE")

INSERT_SUBSCRIPTION_SQL = text(
    "INSERT INTO user_subscriptions (user_id, stripe_customer_id, stripe_subscription_id) "
    "VALUES (:user_id, :customer_id, :subscription_id)"
)
READ_SUBSCRIPTION_SQL = text(
    "SELECT user_id, stripe_customer_id, stripe_subscription_id, plan_id, status::text AS status, "
    "current_period_start, current_period_end, is_canceling_at_period_end, updated_at "
    "FROM user_subscriptions WHERE user_id = :user_id"
)

BillingAppFactory = Callable[..., FastAPI]


class BillingDatabase:
    """Seeds signed-in users and subscriptions, and reads subscriptions back."""

    def __init__(self, auth_db: Any) -> None:
        """Wrap the auth helpers, whose engine no request ever uses."""
        self.auth_db = auth_db

    async def seed_signed_in_user(self, email: str) -> tuple[uuid.UUID, str]:
        """Commit a user and a live session for it; return the id and the raw token."""
        user_id = await self.auth_db.seed_user(email, VALID_PASSWORD)
        raw_token = uuid.uuid4().hex
        await self.auth_db.seed_session(user_id, raw_token)
        return user_id, raw_token

    async def seed_subscription(
        self,
        user_id: uuid.UUID,
        customer_id: str | None,
        subscription_id: str | None = None,
    ) -> None:
        """Commit one user_subscriptions row for the user."""
        async with self.auth_db.engine.begin() as connection:
            await connection.execute(
                INSERT_SUBSCRIPTION_SQL,
                {
                    "user_id": user_id,
                    "customer_id": customer_id,
                    "subscription_id": subscription_id,
                },
            )

    async def read_subscription(self, user_id: uuid.UUID) -> Row[Any] | None:
        """Return the user's subscription row, or None when there is none."""
        async with self.auth_db.engine.connect() as connection:
            result = await connection.execute(READ_SUBSCRIPTION_SQL, {"user_id": user_id})
            return result.one_or_none()


@pytest.fixture
def build_billing_app(
    build_auth_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> BillingAppFactory:
    """Return a factory building the real app with CLIENT_URL pinned and Stripe unset.

    `stripe_client` overrides the route dependency when given; `environment_values` sets extra
    variables, such as the webhook secret, before the application reads its settings.
    """

    def build_application(
        stripe_client: object | None = None,
        environment_values: dict[str, str] | None = None,
    ) -> FastAPI:
        monkeypatch.setenv("CLIENT_URL", CLIENT_URL)
        for name in STRIPE_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        for name, value in (environment_values or {}).items():
            monkeypatch.setenv(name, value)
        application = build_auth_app()
        if stripe_client is not None:
            from app.dependencies.stripe_billing_client import (  # noqa: PLC0415
                get_stripe_billing_client,
            )

            application.dependency_overrides[get_stripe_billing_client] = lambda: stripe_client
        return application

    return build_application


@pytest_asyncio.fixture
async def billing_browser(
    build_billing_app: BillingAppFactory,
    open_auth_browsers: Callable[..., Any],
    stripe_recorder: StripeRecorder,
) -> AsyncIterator[Any]:
    """Yield one browser on an app whose Stripe calls the recorder answers."""
    application = build_billing_app(stripe_client=stripe_recorder.build_client())
    async with open_auth_browsers(application) as browsers:
        yield browsers[0]


@pytest_asyncio.fixture
async def unconfigured_billing_browser(
    build_billing_app: BillingAppFactory, open_auth_browsers: Callable[..., Any]
) -> AsyncIterator[Any]:
    """Yield one browser on an app with no Stripe configuration at all."""
    async with open_auth_browsers(build_billing_app()) as browsers:
        yield browsers[0]


@pytest.fixture
def billing_db(auth_db: Any) -> BillingDatabase:
    """Return the billing seeding and reading helpers."""
    return BillingDatabase(auth_db)
