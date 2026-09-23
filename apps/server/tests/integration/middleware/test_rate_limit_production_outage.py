"""B-7 failure mode: in a deployed environment a Redis outage costs four endpoints, not the API.

A deployed environment never counts in process, because a per-replica count multiplies the
effective limit by the replica count and a client resets it by reconnecting. So when Redis does
not answer, the four auth paths fail closed with 503 `SERVER_RATE_LIMIT_UNAVAILABLE` and every
other route is served normally, with one error log carrying `rate_limiter_unavailable` as the
whole operator signal; Sentry arrives in slice 07 under B-30.

Every test here runs under staging as well as production, because staging is deployed and
multi-replica on exactly the same terms: a limiter that drew the line at production alone left
staging counting per replica, which is very nearly no limit at all, and left the environment
where an outage is rehearsed behaving unlike the one where it happens.

The outage has two forms and each gets its own test, because one test would leave the other path
to inspection. A connection that drops after a successful start is the form settings validation
can never catch, since it checks that `REDIS_URL` is present rather than that the server still
answers; it is reproduced here with a TCP relay in front of the real Redis that the test cuts
mid-run, so the client really does connect, really does serve a request, and really does lose the
connection. A first connection that never succeeds is reproduced by pointing `REDIS_URL` at a
closed port, and needs no relay.

That a deployed environment takes no in-memory path is asserted rather than inspected: after the
outage the tests send more than the global limit of requests to a normal route and require every
one of them to be served. A limiter that quietly fell back to counting in process would reject
the hundred and first, so the run of successes is what rules the fallback out.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import urlsplit

import pytest
import structlog

# Named here rather than imported from the conftest, so this module needs no package import of
# the fixture file that pytest loads for it.
RateLimitAppFactory = Callable[..., Any]
RateLimitClientFactory = Callable[..., Any]

# Both are deployed and multi-replica, so both owe the same outage behavior. Naming them in one
# list keeps a later environment from being added to the application without being asserted here.
DEPLOYED_ENVIRONMENTS = ["production", "staging"]
AUTH_PATHS = [
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
]
UNROUTED_PATH = "/v1/rate-limit-probe"
GLOBAL_REQUEST_LIMIT = 100
REQUESTS_PAST_THE_GLOBAL_LIMIT = GLOBAL_REQUEST_LIMIT + 5
RATE_LIMIT_UNAVAILABLE_MESSAGE = "Rate limiting is unavailable"
RATE_LIMIT_UNAVAILABLE_ENVELOPE = {
    "code": "SERVER_RATE_LIMIT_UNAVAILABLE",
    "error": RATE_LIMIT_UNAVAILABLE_MESSAGE,
}
UNAVAILABLE_LOG_EVENT = "rate_limiter_unavailable"
IN_MEMORY_LOG_EVENT = "rate_limiter_in_memory"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/15"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CLIENT_ADDRESS = "203.0.113.40"
RELAY_CHUNK_BYTES = 4096


class RedisInterrupter:
    """A TCP relay in front of the real Redis, which the test cuts to stage an outage."""

    def __init__(self, server: asyncio.AbstractServer, url: str) -> None:
        """Hold the relay's server, the URL the application connects to, and its connections."""
        self.server = server
        self.url = url
        self.open_writers: list[asyncio.StreamWriter] = []

    async def stop(self) -> None:
        """Close the relay and every connection through it, the way a Redis going down does."""
        for writer in self.open_writers:
            writer.close()
        self.open_writers.clear()
        self.server.close()
        await self.server.wait_closed()


async def pump_bytes(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one direction of a relayed connection until either end closes."""
    with contextlib.suppress(OSError):
        while True:
            chunk = await reader.read(RELAY_CHUNK_BYTES)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    writer.close()


@pytest.fixture
async def redis_interrupter(rate_limit_redis_url: str) -> AsyncIterator[RedisInterrupter]:
    """Yield a relay to the real Redis, listening on a local port, stopped at the end."""
    parts = urlsplit(rate_limit_redis_url)
    upstream_host = parts.hostname or "127.0.0.1"
    upstream_port = parts.port or 6379
    relay: RedisInterrupter

    async def serve_relayed_connection(
        client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        """Open the upstream connection and copy bytes both ways until one side closes."""
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                upstream_host, upstream_port
            )
        except OSError:
            client_writer.close()
            return
        relay.open_writers.extend([client_writer, upstream_writer])
        await asyncio.gather(
            pump_bytes(client_reader, upstream_writer),
            pump_bytes(upstream_reader, client_writer),
            return_exceptions=True,
        )

    server = await asyncio.start_server(serve_relayed_connection, "127.0.0.1", 0)
    relay_port = int(server.sockets[0].getsockname()[1])
    relay = RedisInterrupter(server, f"redis://127.0.0.1:{relay_port}{parts.path}")
    try:
        yield relay
    finally:
        await relay.stop()


@pytest.mark.integration
@pytest.mark.parametrize("environment", DEPLOYED_ENVIRONMENTS)
async def test_b7_a_redis_outage_after_a_successful_start_fails_only_the_auth_paths_closed(
    environment: str,
    redis_interrupter: RedisInterrupter,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """A connection lost after the first served request is the form settings cannot catch."""
    application = build_rate_limit_app(redis_interrupter.url, environment=environment)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        before_outage = await client.post(AUTH_PATHS[0], headers=CSRF_HEADERS)
        await redis_interrupter.stop()
        with structlog.testing.capture_logs() as captured_events:
            auth_responses = [
                await client.post(auth_path, headers=CSRF_HEADERS) for auth_path in AUTH_PATHS
            ]
            served = [
                await client.get(UNROUTED_PATH) for _ in range(REQUESTS_PAST_THE_GLOBAL_LIMIT)
            ]

    assert before_outage.status_code == 404, "the relay must have carried the first request"
    for auth_response in auth_responses:
        assert auth_response.status_code == 503
        assert auth_response.json() == RATE_LIMIT_UNAVAILABLE_ENVELOPE
    assert all(response.status_code == 404 for response in served)
    captured_names = [event.get("event") for event in captured_events]
    assert UNAVAILABLE_LOG_EVENT in captured_names, captured_names
    assert IN_MEMORY_LOG_EVENT not in captured_names, captured_names


@pytest.mark.integration
@pytest.mark.parametrize("environment", DEPLOYED_ENVIRONMENTS)
async def test_b7_a_redis_that_never_connects_fails_only_the_auth_paths_closed(
    environment: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """`REDIS_URL` is set and nothing answers at it, which settings validation cannot see."""
    application = build_rate_limit_app(UNREACHABLE_REDIS_URL, environment=environment)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
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
    assert all(response.status_code == 404 for response in served)
    captured_names = [event.get("event") for event in captured_events]
    assert UNAVAILABLE_LOG_EVENT in captured_names, captured_names
    assert IN_MEMORY_LOG_EVENT not in captured_names, captured_names
