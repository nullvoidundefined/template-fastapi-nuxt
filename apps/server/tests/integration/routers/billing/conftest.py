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

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine

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


# The webhook signing secret, built from parts at run time so no credential-shaped literal
# appears in this source (R-108). A second value signs deliveries that must fail verification.
WEBHOOK_SIGNING_VALUE = "_".join(("whsec", "test", "placeholder"))
WRONG_SIGNING_VALUE = "_".join(("whsec", "test", "impostor"))
WEBHOOK_PATH = "/v1/billing/webhook"
AUTH_BASE_URL = "https://testserver"
WEBHOOK_CLIENT_ADDRESS = "198.51.100.7"

INSERT_USER_WITH_ID_SQL = text(
    "INSERT INTO users (id, email, password_hash) VALUES (:user_id, :email, :password_hash)"
)
READ_LEDGER_SQL = text(
    "SELECT stripe_event_id, event_type, status::text AS status, attempted_at, processed_at "
    "FROM billing_webhook_events WHERE stripe_event_id = :event_id"
)
SEED_LEDGER_SQL = text(
    "INSERT INTO billing_webhook_events (stripe_event_id, event_type, status, attempted_at) "
    "VALUES (:event_id, :event_type, CAST(:status AS billing_webhook_event_status), "
    "now() - make_interval(mins => :minutes_ago))"
)
DELETE_LEDGER_SQL = text("DELETE FROM billing_webhook_events WHERE stripe_event_id = :event_id")


def make_stripe_id(prefix: str) -> str:
    """Return a unique Stripe-shaped identifier with the given prefix."""
    return f"{prefix}_test_{uuid.uuid4().hex}"


def build_stripe_event(
    event_type: str, data_object: dict[str, Any], event_id: str | None = None
) -> dict[str, Any]:
    """Return a Stripe event envelope around one object, as Stripe delivers it."""
    return {
        "id": event_id or make_stripe_id("evt"),
        "object": "event",
        "api_version": "2025-03-31.basil",
        "created": int(time.time()),
        "type": event_type,
        "livemode": False,
        "data": {"object": data_object},
    }


def sign_stripe_payload(payload: bytes, signing_value: str, timestamp: int | None = None) -> str:
    """Return a `Stripe-Signature` header for the payload, computed as Stripe computes it.

    The v1 scheme is an HMAC-SHA256 over `<timestamp>.<payload>` keyed with the endpoint's signing
    secret, which is exactly what `stripe.WebhookSignature.verify_header` recomputes.
    """
    signed_at = int(time.time()) if timestamp is None else timestamp
    signed_payload = f"{signed_at}.".encode() + payload
    digest = hmac.new(signing_value.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_at},v1={digest}"


class WebhookSender:
    """Delivers signed events to the webhook as Stripe would, and reads the ledger back.

    The client carries no `X-Requested-With` header, because Stripe sends none, so every delivery
    in these tests also proves the webhook's CSRF exemption. Every event id sent or seeded is
    recorded, and the ledger rows are deleted when the test ends.
    """

    def __init__(self, client: httpx.AsyncClient, engine: AsyncEngine) -> None:
        """Record the client that reaches the app and the engine that reads the ledger."""
        self.client = client
        self.engine = engine
        self.event_ids: set[str] = set()

    async def deliver(
        self,
        event: dict[str, Any],
        signing_value: str = WEBHOOK_SIGNING_VALUE,
        signature: str | None = None,
        is_signed: bool = True,
    ) -> httpx.Response:
        """POST the event as raw JSON with a signature, or with the one given, or with none."""
        self.event_ids.add(event["id"])
        payload = json.dumps(event).encode()
        headers = {"Content-Type": "application/json"}
        if is_signed:
            headers["Stripe-Signature"] = signature or sign_stripe_payload(payload, signing_value)
        return await self.client.post(WEBHOOK_PATH, content=payload, headers=headers)

    async def read_ledger(self, event_id: str) -> list[Row[Any]]:
        """Return every ledger row for the event id: none, or exactly one."""
        async with self.engine.connect() as connection:
            result = await connection.execute(READ_LEDGER_SQL, {"event_id": event_id})
            return list(result)

    async def seed_ledger(
        self, event_id: str, event_type: str, status: str, minutes_ago: int
    ) -> None:
        """Commit a ledger row in the given state, attempted the given minutes ago."""
        self.event_ids.add(event_id)
        async with self.engine.begin() as connection:
            await connection.execute(
                SEED_LEDGER_SQL,
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": status,
                    "minutes_ago": minutes_ago,
                },
            )

    async def seed_user_with_id(self, user_id: uuid.UUID, email: str) -> None:
        """Commit a user with a chosen id, as a user created after an event named it would be."""
        async with self.engine.begin() as connection:
            await connection.execute(
                INSERT_USER_WITH_ID_SQL,
                {"user_id": user_id, "email": email, "password_hash": VALID_PASSWORD},
            )

    async def delete_ledger_rows(self) -> None:
        """Delete every ledger row this sender created or seeded."""
        async with self.engine.begin() as connection:
            for event_id in self.event_ids:
                await connection.execute(DELETE_LEDGER_SQL, {"event_id": event_id})


@asynccontextmanager
async def open_webhook_sender(
    application: FastAPI, engine: AsyncEngine
) -> AsyncIterator[WebhookSender]:
    """Run the app's lifespan and yield a sender whose client has no CSRF header."""
    transport = httpx.ASGITransport(
        app=application, client=(WEBHOOK_CLIENT_ADDRESS, 443), raise_app_exceptions=False
    )
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(transport=transport, base_url=AUTH_BASE_URL) as client,
    ):
        sender = WebhookSender(client, engine)
        try:
            yield sender
        finally:
            await sender.delete_ledger_rows()


@pytest_asyncio.fixture
async def webhook_sender(
    build_billing_app: BillingAppFactory, auth_db: Any
) -> AsyncIterator[WebhookSender]:
    """Yield a sender on an app configured with the webhook signing secret."""
    application = build_billing_app(
        environment_values={"STRIPE_WEBHOOK_SECRET": WEBHOOK_SIGNING_VALUE}
    )
    async with open_webhook_sender(application, auth_db.engine) as sender:
        yield sender


@pytest_asyncio.fixture
async def unconfigured_webhook_sender(
    build_billing_app: BillingAppFactory, auth_db: Any
) -> AsyncIterator[WebhookSender]:
    """Yield a sender on an app with no webhook signing secret configured."""
    async with open_webhook_sender(build_billing_app(), auth_db.engine) as sender:
        yield sender
