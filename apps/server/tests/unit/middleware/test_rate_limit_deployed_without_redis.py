"""B-7: a deployed environment with no REDIS_URL at all takes the outage path, not the fallback.

Settings refuse to start production without `REDIS_URL`, so production can never reach the
limiter unconfigured; staging can, because the same validator does not require the variable
there. That gap is the one this module covers. Staging is deployed and multi-replica exactly as
production is, so an in-process count there multiplies the effective limit by the replica count
and a client resets it by reconnecting, which is very nearly no limit at all on the four paths
that exist to bound credential guessing.

The missing variable is therefore treated as the outage it is: the four auth paths fail closed
with 503 `SERVER_RATE_LIMIT_UNAVAILABLE`, every other route is served, and the operator gets the
same `rate_limiter_unavailable` line, whose `error_type` says which of the two shapes it is, a
variable that was never set rather than a server that stopped answering.

That no in-process count happens is asserted rather than inspected: the test sends more than the
global limit of requests to a normal route and requires every one to be served, which a limiter
counting in memory could not do, and requires the `rate_limiter_in_memory` warning never to
appear. No Redis is needed and none is touched, since the point is that no URL is configured.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
import structlog
from fastapi import FastAPI

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
TEST_BASE_URL = "http://testserver"
AUTH_PATHS = [
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
]
UNROUTED_PATH = "/v1/rate-limit-probe"
GLOBAL_REQUEST_LIMIT = 100
REQUESTS_PAST_THE_GLOBAL_LIMIT = GLOBAL_REQUEST_LIMIT + 5
RATE_LIMIT_UNAVAILABLE_ENVELOPE = {
    "code": "SERVER_RATE_LIMIT_UNAVAILABLE",
    "error": "Rate limiting is unavailable",
}
UNAVAILABLE_LOG_EVENT = "rate_limiter_unavailable"
IN_MEMORY_LOG_EVENT = "rate_limiter_in_memory"
MISSING_URL_ERROR_TYPE = "MissingRedisUrlError"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CORS_ORIGIN = "https://client.example.test"
CLIENT_ADDRESS = "203.0.113.60"
CLIENT_PORT = 54321
# Production is absent deliberately: its settings validator refuses to start without REDIS_URL,
# so the unconfigured deployed environment is staging and only staging.
DEPLOYED_ENVIRONMENT_WITHOUT_REQUIRED_REDIS = "staging"

ApplicationFactory = Callable[[], FastAPI]


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (import after the env is patched)

    get_settings.cache_clear()


@pytest.fixture
def build_staging_app_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ApplicationFactory]:
    """Return a factory building the real application under `staging` with no REDIS_URL set."""

    def build_application() -> FastAPI:
        monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
        monkeypatch.setenv("ENVIRONMENT", DEPLOYED_ENVIRONMENT_WITHOUT_REQUIRED_REDIS)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("CORS_ORIGIN", CORS_ORIGIN)
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
        from app.main import create_app  # noqa: PLC0415 (import after the env is patched)

        clear_settings_cache()
        return create_app()

    yield build_application
    clear_settings_cache()


@asynccontextmanager
async def open_client(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client whose requests reach the application from one fixed peer address."""
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(
            app=application,
            client=(CLIENT_ADDRESS, CLIENT_PORT),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            yield client


async def test_b7_a_deployed_environment_without_redis_fails_the_auth_paths_closed(
    build_staging_app_without_redis: ApplicationFactory,
) -> None:
    """An unset REDIS_URL in staging must cost the four auth paths, never become a local count."""
    application = build_staging_app_without_redis()

    async with open_client(application) as client:
        with structlog.testing.capture_logs() as captured_events:
            auth_responses = [
                await client.post(auth_path, headers=CSRF_HEADERS) for auth_path in AUTH_PATHS
            ]
            served = [
                await client.get(UNROUTED_PATH) for _ in range(REQUESTS_PAST_THE_GLOBAL_LIMIT)
            ]

    for auth_response in auth_responses:
        assert auth_response.status_code == 503
        assert auth_response.json() == RATE_LIMIT_UNAVAILABLE_ENVELOPE
    # Every one of them, past the global limit: an in-process count could not do that.
    served_statuses = {response.status_code for response in served}
    assert served_statuses == {404}, served_statuses
    captured_names = [event.get("event") for event in captured_events]
    assert IN_MEMORY_LOG_EVENT not in captured_names, captured_names
    unavailable_events = [
        event for event in captured_events if event.get("event") == UNAVAILABLE_LOG_EVENT
    ]
    assert unavailable_events, captured_names
    assert all(
        event.get("error_type") == MISSING_URL_ERROR_TYPE for event in unavailable_events
    ), unavailable_events
