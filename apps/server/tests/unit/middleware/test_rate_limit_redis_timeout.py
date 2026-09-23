"""B-7 failure mode: a Redis that answers nothing costs four endpoints rather than the API.

The outage this module stages is the one no connection error reports. The port completes the TCP
handshake, accepts every byte the client sends, and never answers, which is what a failover in
progress or a partition that dropped packets without sending a reset looks like from the client's
side. Nothing in the request path bounds that wait by itself: the rate limiter is registered
outside `RequestTimeoutMiddleware`, so the 30 second timeout sits inside the limiter and can never
fire while the limiter is blocked, and redis-py leaves both socket timeouts unset unless the
caller passes them. Without them every non-exempt route hangs for as long as the outage lasts,
which is unbounded, instead of costing the four auth paths their 503.

The assertion is therefore about time as much as about status. The request block runs under
`asyncio.timeout`, so a limiter that waits forever fails this test in seconds with a cancellation
rather than hanging the suite until someone kills it, and the deadline is far longer than the
timeouts the limiter is supposed to use, so an ordinarily slow machine does not fail it.

No real Redis is needed and none is touched: the listener is opened by the test on a loopback port
the operating system chooses.
"""

import asyncio
import contextlib
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
RATE_LIMIT_UNAVAILABLE_ENVELOPE = {
    "code": "SERVER_RATE_LIMIT_UNAVAILABLE",
    "error": "Rate limiting is unavailable",
}
UNAVAILABLE_LOG_EVENT = "rate_limiter_unavailable"
IN_MEMORY_LOG_EVENT = "rate_limiter_in_memory"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CORS_ORIGIN = "https://client.example.test"
CLIENT_ADDRESS = "203.0.113.50"
CLIENT_PORT = 54321
# Generous next to the two second socket timeouts the limiter sets, and finite so a limiter that
# reverts to an unbounded wait fails here instead of stalling every later test behind it.
TEST_DEADLINE_SECONDS = 25.0
READ_CHUNK_BYTES = 4096

ApplicationFactory = Callable[[str], FastAPI]


class SilentRedis:
    """A listener that accepts connections, swallows every command, and never replies."""

    def __init__(self, server: asyncio.AbstractServer, url: str) -> None:
        """Hold the listening server, the URL the application connects to, and its connections."""
        self.server = server
        self.url = url
        self.open_writers: list[asyncio.StreamWriter] = []

    async def stop(self) -> None:
        """Close every held connection and stop listening, so no task outlives the test."""
        for writer in self.open_writers:
            writer.close()
        self.open_writers.clear()
        self.server.close()
        await self.server.wait_closed()


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (import after the env is patched)

    get_settings.cache_clear()


@pytest.fixture
async def silent_redis() -> AsyncIterator[SilentRedis]:
    """Yield a listener on a loopback port that reads forever and answers nothing."""
    listener: SilentRedis

    async def swallow_every_command(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Read whatever the client sends until it goes away, without ever writing a reply.

        The bytes are read rather than ignored so the client's own writes complete and it ends up
        waiting on a response, which is the state a hung Redis leaves it in; a handler that never
        read would eventually block the client in its send instead, which is a different failure.
        """
        listener.open_writers.append(writer)
        with contextlib.suppress(OSError):
            while await reader.read(READ_CHUNK_BYTES):
                pass
        writer.close()

    server = await asyncio.start_server(swallow_every_command, "127.0.0.1", 0)
    listening_port = int(server.sockets[0].getsockname()[1])
    listener = SilentRedis(server, f"redis://127.0.0.1:{listening_port}/0")
    try:
        yield listener
    finally:
        await listener.stop()


@pytest.fixture
def build_production_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApplicationFactory]:
    """Return a factory building the real application under `production` against a given Redis."""

    def build_application(redis_url: str) -> FastAPI:
        monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("REDIS_URL", redis_url)
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


async def test_b7_a_redis_that_answers_nothing_costs_the_auth_paths_rather_than_every_route(
    silent_redis: SilentRedis,
    build_production_app: ApplicationFactory,
) -> None:
    """The limiter must give up on a silent Redis and take the outage path within seconds."""
    application = build_production_app(silent_redis.url)

    async with open_client(application) as client:
        with structlog.testing.capture_logs() as captured_events:
            async with asyncio.timeout(TEST_DEADLINE_SECONDS):
                # Each request waits out the limiter's socket timeout, and redis-py serializes
                # those waits behind its pool, so issuing them together saves nothing and the
                # sequential form is the one that reads.
                auth_responses = [
                    await client.post(auth_path, headers=CSRF_HEADERS) for auth_path in AUTH_PATHS
                ]
                served = await client.get(UNROUTED_PATH)

    for auth_response in auth_responses:
        assert auth_response.status_code == 503
        assert auth_response.json() == RATE_LIMIT_UNAVAILABLE_ENVELOPE
    assert served.status_code == 404, "a normal route is served while Redis is silent"
    captured_names = [event.get("event") for event in captured_events]
    assert UNAVAILABLE_LOG_EVENT in captured_names, captured_names
    assert IN_MEMORY_LOG_EVENT not in captured_names, captured_names
