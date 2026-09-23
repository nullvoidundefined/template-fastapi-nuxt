"""B-46: without Redis the limiter counts in process, and says so exactly once.

The suite runs without Redis, so `environment="test"` with no `REDIS_URL` has to keep limiting
rather than switching the protection off, otherwise no test in the tree would ever exercise it.
The degraded mode is visible instead of invisible: one `rate_limiter_in_memory` warning per
process, not one per request, so the line means "this process is counting locally" rather than
drowning the log.

The requests go through the real `create_app()`, not through a hand-built middleware stack, so
these tests also hold the registration slot in `app.main.register_middleware` in place: a limiter
that exists but is never added to the chain fails them exactly as a missing one does. The paths
below are asserted as "not 429" rather than as a status code of their own, because slice 03 mounts
real handlers on them and the assertion here is about the limiter, not about routing.

The in-memory counter belongs to the application instance that owns it. The suite builds an
application per test and makes far more than one hundred requests from the same client address in
one process, so a counter shared across instances would start rejecting unrelated tests partway
through a run; the last test below pins that.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
import structlog
from fastapi import FastAPI

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
TEST_BASE_URL = "http://testserver"
AUTH_PATH = "/v1/auth/login"
AUTH_REQUEST_LIMIT = 10
RATE_LIMIT_WINDOW_SECONDS = 900
RATE_LIMIT_EXCEEDED_MESSAGE = "Too many requests"
IN_MEMORY_LOG_EVENT = "rate_limiter_in_memory"
CLIENT_ADDRESS = "203.0.113.30"
CLIENT_PORT = 54321

ApplicationFactory = Callable[[], FastAPI]


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (missing until implemented)

    get_settings.cache_clear()


@pytest.fixture
def build_app_without_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApplicationFactory]:
    """Return a factory building the real application under `test` with no REDIS_URL at all."""

    def build_application() -> FastAPI:
        monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.delenv("REDIS_URL", raising=False)
        from app.main import create_app  # noqa: PLC0415 (missing until implemented)

        clear_settings_cache()
        return create_app()

    yield build_application
    clear_settings_cache()


@asynccontextmanager
async def open_client(
    application: FastAPI, client_address: str
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client whose requests reach the application from one fixed peer address."""
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(
            app=application,
            client=(client_address, CLIENT_PORT),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            yield client


async def test_b46_requests_without_redis_share_one_in_memory_auth_bucket(
    build_app_without_redis: ApplicationFactory,
) -> None:
    """The eleventh request answers 429, so the ten before it were counted in one bucket."""
    application = build_app_without_redis()

    async with open_client(application, CLIENT_ADDRESS) as client:
        allowed = [await client.get(AUTH_PATH) for _ in range(AUTH_REQUEST_LIMIT)]
        rejected = await client.get(AUTH_PATH)

    assert all(response.status_code != 429 for response in allowed)
    assert rejected.status_code == 429
    assert rejected.json() == {
        "code": "RATE_LIMIT_EXCEEDED",
        "error": RATE_LIMIT_EXCEEDED_MESSAGE,
    }
    assert 0 < int(rejected.headers["Retry-After"]) <= RATE_LIMIT_WINDOW_SECONDS


async def test_b46_the_in_memory_fallback_is_logged_exactly_once_across_two_requests(
    build_app_without_redis: ApplicationFactory,
) -> None:
    """One warning per process makes the degraded mode visible without flooding the log."""
    application = build_app_without_redis()

    with structlog.testing.capture_logs() as captured_events:
        async with open_client(application, CLIENT_ADDRESS) as client:
            await client.get(AUTH_PATH)
            await client.get(AUTH_PATH)

    fallback_events = [
        event for event in captured_events if event.get("event") == IN_MEMORY_LOG_EVENT
    ]
    assert len(fallback_events) == 1, [event.get("event") for event in captured_events]


async def test_b46_each_application_starts_with_an_empty_in_memory_count(
    build_app_without_redis: ApplicationFactory,
) -> None:
    """A count shared between applications would reject unrelated tests later in the run."""
    exhausted_application = build_app_without_redis()
    async with open_client(exhausted_application, CLIENT_ADDRESS) as client:
        for _ in range(AUTH_REQUEST_LIMIT):
            await client.get(AUTH_PATH)
        rejected = await client.get(AUTH_PATH)
    assert rejected.status_code == 429

    fresh_application = build_app_without_redis()
    async with open_client(fresh_application, CLIENT_ADDRESS) as client:
        served = await client.get(AUTH_PATH)

    assert served.status_code != 429
