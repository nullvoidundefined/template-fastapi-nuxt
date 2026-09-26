"""Shared fixtures: the app under test, HTTP clients that run its lifespan, and log capture.

The app is built through the public factory `app.main.create_app()` after the environment is
set, so every test exercises the same assembly uvicorn runs. Both application factories here,
`server_app` and `build_server_app`, set the database and Redis URLs to a closed local port, so
any test that does not override them proves it never needs a reachable Postgres and never touches
whatever Redis happens to be running on the machine. Both have to set them: an unset variable is
read from the surrounding shell, so a fixture that left `REDIS_URL` alone would count its
requests into a real Redis on any developer machine or CI runner that exports one.

`build_server_app` is the test application factory: it builds the app through that same public
factory under a chosen environment and then mounts a test-only router the calling test supplies,
so a test can reach a route that raises the exception it wants to observe. `create_app()` itself
never mounts that router, and `tests/unit/test_main_exception_handlers.py` asserts that it does not.
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, MutableMapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

import httpx
import pytest
import structlog
from fastapi import APIRouter, FastAPI
from pydantic import SecretStr

if TYPE_CHECKING:
    from app.clients.stripe import StripeBillingClient

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
TEST_BASE_URL = "http://testserver"
# The rate limiter counts in Redis whenever REDIS_URL is set, so this URL has to name an address
# that nothing can ever be listening on. Pointing it at the default Redis port made every unit
# test write real rate-limit keys into whichever Redis happened to be running on the machine,
# keyed on the 127.0.0.1 address httpx reports, and because the suite makes far more than the
# global limit of one hundred requests per fifteen minutes from that one address, every run
# started inside the previous run's window already over the limit and answered 429 to tests that
# have nothing to do with rate limiting. Port 1 is closed, so the limiter takes its in-process
# fallback deterministically, which is the same guarantee UNREACHABLE_DATABASE_URL gives for
# Postgres. A test that genuinely needs a reachable Redis sets its own URL from TEST_REDIS_URL,
# as the integration fixtures under tests/integration/middleware do.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def database_url() -> str:
    """Return the database URL the app under test reads from DATABASE_URL."""
    return UNREACHABLE_DATABASE_URL


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next get_settings() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (missing until implemented)

    get_settings.cache_clear()


@pytest.fixture
def server_app(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    """Build the app through create_app() with DATABASE_URL, ENVIRONMENT, and REDIS_URL patched.

    REDIS_URL is set here for the same reason `build_server_app` sets it: left alone, the app
    under test reads whatever the surrounding shell exports, and the rate limiter then counts
    every request of this suite into a real Redis someone else is using. This fixture backs
    `api_client` and `captured_log_events`, which about eleven test modules depend on, so the
    variable has to be pinned here rather than only in the other factory.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
    from app.main import create_app  # noqa: PLC0415 (missing until implemented)

    clear_settings_cache()
    application = create_app()
    yield application
    clear_settings_cache()


@pytest.fixture
async def api_client(server_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's lifespan, so the engine exists, and yield a client bound to the app."""
    async with server_app.router.lifespan_context(server_app):
        transport = httpx.ASGITransport(app=server_app)
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            yield client


@pytest.fixture
def build_server_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[ServerAppFactory]:
    """Return a factory that builds the app under a chosen environment and mounts a test router.

    The factory patches database, environment, and Redis settings and supplies defaults for
    CORS and trusted proxies without overriding a test's explicit configuration. It clears the
    settings cache, calls the public `create_app()`, and includes the caller's test-only router, so
    the assembly under test is the one uvicorn runs and the test-only routes are never part of it.
    """

    def build_application(
        test_only_router: APIRouter | None = None,
        environment: str = "test",
        database_url: str = UNREACHABLE_DATABASE_URL,
    ) -> FastAPI:
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
        monkeypatch.setenv(
            "CORS_ORIGIN", os.environ.get("CORS_ORIGIN", "https://client.example.test")
        )
        monkeypatch.setenv(
            "FORWARDED_ALLOW_IPS", os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
        )
        from app.main import create_app  # noqa: PLC0415 (missing until implemented)

        clear_settings_cache()
        application = create_app()
        if test_only_router is not None:
            application.include_router(test_only_router)
        return application

    yield build_application
    clear_settings_cache()


@pytest.fixture
def build_api_client() -> ApiClientFactory:
    """Return a factory yielding a client bound to one app, with that app's lifespan running.

    The transport sets `raise_app_exceptions=False` so an exception a route raises comes back as
    the response the registered handler produced, rather than being re-raised into the test by
    Starlette's server-error middleware, which always re-raises after it answers.
    """

    @asynccontextmanager
    async def build_client(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
                yield client

    return build_client


@pytest.fixture
def captured_log_events(server_app: FastAPI) -> Iterator[list[dict[str, Any]]]:
    """Record every structlog event after the app's own processors run, up to the renderer.

    The recorder is spliced into the processor chain that create_app() configured, just before
    the final renderer, so the captured event dict holds exactly what the configured chain
    (including any context merging) produced for that line.
    """
    original_config = structlog.get_config()
    configured_processors = list(original_config["processors"])
    assert configured_processors, "create_app() must configure a structlog processor chain"
    recorded_events: list[dict[str, Any]] = []

    def record_event_dict(
        _logger: structlog.typing.WrappedLogger,
        _method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> Mapping[str, Any]:
        recorded_events.append(dict(event_dict))
        return event_dict

    structlog.configure(
        processors=[*configured_processors[:-1], record_event_dict, configured_processors[-1]],
        cache_logger_on_first_use=False,
    )
    yield recorded_events
    structlog.configure(**original_config)


# Built from parts at run time, so no credential-shaped literal appears in this source (R-108).
STRIPE_TEST_API_KEY = "_".join(("sk", "test", "placeholder"))
STRIPE_CHECKOUT_SESSIONS_PATH = "/v1/checkout/sessions"
STRIPE_PORTAL_SESSIONS_PATH = "/v1/billing_portal/sessions"


@dataclass
class StripeRecorder:
    """Answers the Stripe API over `httpx.MockTransport` and records every request it received.

    The Stripe client under test is the real one, built by its own factory, so what a test asserts
    is the HTTP request the SDK really sent: its path, its form fields, its headers, and its
    timeout. Each answer carries a URL numbered by the request that produced it, so a second
    Checkout session would carry a different URL than the first and a replay is recognizable.
    Setting `failure_status` makes every answer a Stripe API error with that status instead.
    """

    requests: list[httpx.Request] = field(default_factory=list)
    failure_status: int | None = None

    def answer(self, request: httpx.Request) -> httpx.Response:
        """Record the request and answer it as Stripe would."""
        self.requests.append(request)
        number = len(self.requests)
        if self.failure_status is not None:
            error = {"error": {"type": "api_error", "message": "Test-only Stripe failure"}}
            return httpx.Response(self.failure_status, json=error)
        if request.url.path == STRIPE_CHECKOUT_SESSIONS_PATH:
            return httpx.Response(
                200,
                json={
                    "id": f"cs_test_{number}",
                    "object": "checkout.session",
                    "url": f"https://checkout.stripe.test/c/pay/cs_test_{number}",
                },
            )
        if request.url.path == STRIPE_PORTAL_SESSIONS_PATH:
            return httpx.Response(
                200,
                json={
                    "id": f"bps_test_{number}",
                    "object": "billing_portal.session",
                    "url": f"https://billing.stripe.test/p/session/bps_test_{number}",
                },
            )
        return httpx.Response(404, json={"error": {"type": "invalid_request_error"}})

    def read_form(self, index: int = 0) -> dict[str, str]:
        """Return the form fields of the recorded request at `index`, as Stripe encodes them."""
        return dict(parse_qsl(self.requests[index].content.decode()))

    def build_client(self, api_base: str | None = None) -> "StripeBillingClient":
        """Return the real Stripe billing client whose HTTP calls this recorder answers.

        The transport is swapped on the SDK's own httpx client after the client's factory built
        it, so the timeout the factory configured is still the one every request carries.
        """
        from app.clients.stripe import (  # noqa: PLC0415 (missing until implemented)
            StripeBillingClient,
            build_stripe_http_client,
        )

        http_client = build_stripe_http_client()
        http_client._client_async = httpx.AsyncClient(  # noqa: SLF001 (the SDK's only seam)
            transport=httpx.MockTransport(self.answer)
        )
        return StripeBillingClient(
            SecretStr(STRIPE_TEST_API_KEY), api_base=api_base, http_client=http_client
        )


@pytest.fixture
def stripe_recorder() -> StripeRecorder:
    """Return a fresh recorder standing in for the Stripe API."""
    return StripeRecorder()
