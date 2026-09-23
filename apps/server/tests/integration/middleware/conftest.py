"""Fixtures for the rate-limit integration tests: a flushed Redis, the app, and its clients.

Every test here counts requests in a Redis every replica shares, so each one needs a database
holding its own state rather than whatever an earlier test, or an earlier run inside the same
fifteen-minute window, left behind. The fixtures point the application at a Redis database
reserved for these tests and flush it before the test body runs, so a rerun a second later counts
from zero.

The application is built through the public `create_app()` factory under `environment="production"`,
because production is the configuration B-7 describes: Redis is mandatory there, the in-memory
counter is unreachable on every code path, and the four auth paths fail closed when Redis does not
answer. The Postgres URL points at a closed local port, because nothing here touches the database;
the lifespan still runs, so the readiness route has the engine it reads.

Uvicorn is not running in these tests, so the proxy-header handling it would do is supplied by the
tests that need it, which wrap the application in uvicorn's own `ProxyHeadersMiddleware` and set
the transport's client address to the proxy. `FORWARDED_ALLOW_IPS` is still set to the same proxy
address, so the settings the application reads match the wrapper the requests pass through.
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.exceptions import RedisError

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
TEST_BASE_URL = "http://testserver"
# A Redis database of its own, so flushing before a test never touches the queue or the cache
# another suite is using on the same server.
RATE_LIMIT_REDIS_DATABASE = 15
# The reverse proxy in front of the API. Uvicorn honors `X-Forwarded-For` only from this address,
# and the tests that drive a direct request use a different one.
PROXY_ADDRESS = "10.10.0.2"
CORS_ORIGIN = "https://client.example.test"
CLIENT_PORT = 54321

RateLimitAppFactory = Callable[..., FastAPI]
RateLimitClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (missing until implemented)

    get_settings.cache_clear()


@pytest.fixture
def configured_redis_url() -> str:
    """Return TEST_REDIS_URL redirected at the rate limiter's reserved database, or skip."""
    test_redis_url = os.environ.get("TEST_REDIS_URL")
    if not test_redis_url:
        pytest.skip("IAN-171: TEST_REDIS_URL is unset; the rate-limit tests need a real Redis")
    parts = urlsplit(test_redis_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{RATE_LIMIT_REDIS_DATABASE}", parts.query, parts.fragment)
    )


@pytest.fixture
async def rate_limit_redis_client(configured_redis_url: str) -> AsyncIterator[Redis]:
    """Yield a client on the flushed rate-limit database, so every test counts from zero.

    The flush is also the connection check: a Redis that cannot be reached skips the test with a
    reason naming the variable, rather than raising out of setup and reporting an error that says
    nothing about what the test needed.
    """
    redis_client: Redis = Redis.from_url(configured_redis_url)
    try:
        await redis_client.flushdb()
    except (OSError, RedisError):
        await redis_client.aclose()
        pytest.skip("IAN-171: the Redis at TEST_REDIS_URL did not answer; these tests need it")
    try:
        yield redis_client
    finally:
        await redis_client.aclose()


@pytest.fixture
def rate_limit_redis_url(rate_limit_redis_client: Redis, configured_redis_url: str) -> str:
    """Return the flushed database's URL, for a test that counts but inspects no key."""
    return configured_redis_url


@pytest.fixture
def build_rate_limit_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[RateLimitAppFactory]:
    """Return a factory building the real application against a chosen Redis URL."""

    def build_application(redis_url: str, environment: str = "production") -> FastAPI:
        monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("REDIS_URL", redis_url)
        monkeypatch.setenv("CORS_ORIGIN", CORS_ORIGIN)
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", PROXY_ADDRESS)
        from app.main import create_app  # noqa: PLC0415 (missing until implemented)

        clear_settings_cache()
        return create_app()

    yield build_application
    clear_settings_cache()


@pytest.fixture
def open_rate_limited_client() -> RateLimitClientFactory:
    """Return a factory yielding a client whose requests arrive from one fixed peer address.

    `asgi_app` is the application the transport actually calls, which is the application itself
    unless the test wrapped it in uvicorn's proxy-header middleware; the lifespan is always run on
    the FastAPI application underneath, so the readiness route has its engine either way.
    """

    @asynccontextmanager
    async def open_client(
        application: FastAPI, client_address: str, asgi_app: Any = None
    ) -> AsyncIterator[httpx.AsyncClient]:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(
                app=application if asgi_app is None else asgi_app,
                client=(client_address, CLIENT_PORT),
                raise_app_exceptions=False,
            )
            async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
                yield client

    return open_client
