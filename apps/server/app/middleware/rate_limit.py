"""Bounds how many requests one client may make in a window (spec B-7, B-46).

The key is the client address uvicorn resolved, read from `scope["client"]`. This module never
parses `X-Forwarded-For` itself, and that restraint is the whole protection: every entry in that
header except the last is supplied by the client, so a limiter that read it would let anyone
rotate buckets at will by prepending an address. Uvicorn runs with `--proxy-headers` and honors
the header only from the addresses in `FORWARDED_ALLOW_IPS`, so a request arriving from anywhere
else is keyed on its own peer address.

Counting is one atomic Redis operation. `INCR` followed by a separate `EXPIRE` is two round trips:
concurrent requests can all read the same value and all be admitted, and a process that dies
between the two leaves a key with no expiry that never resets, locking the client out for good.
The script below increments and initializes the expiry together, and arms the expiry only when the
key carries none, so the window is fixed rather than sliding forward on every request.

Without Redis the limiter counts in this process, for development and tests only, and says so once
so the degraded mode is visible rather than silent. Production never reaches that path: a
per-replica count multiplies the effective limit by the replica count and a client resets it by
reconnecting, so when Redis is gone the four auth paths fail closed instead and everything else is
served. One `rate_limiter_unavailable` log line is the whole operator signal in this slice; the
Sentry report arrives in slice 07 under B-30.
"""

import time
from collections.abc import Awaitable
from typing import cast

import redis.asyncio as redis_asyncio
import structlog
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Receive, Scope, Send

from app.constants.error_codes import ErrorCode
from app.constants.exempt_paths import RATE_LIMIT_EXEMPT_PATHS
from app.constants.rate_limits import (
    AUTH_RATE_LIMITED_PATHS,
    AUTH_RATE_LIMITED_ROUTES,
    AUTH_REQUEST_LIMIT,
    GLOBAL_REQUEST_LIMIT,
    RATE_LIMIT_WINDOW_SECONDS,
)
from app.core.settings import Settings
from app.errors import send_error_envelope

RATE_LIMIT_EXCEEDED_MESSAGE = "Too many requests"
RATE_LIMIT_UNAVAILABLE_MESSAGE = "Rate limiting is unavailable"
# Both are deployed and multi-replica, so neither may ever count in process: a per-replica
# count multiplies the effective limit by the replica count and a client resets it by
# reconnecting. `app/db/engine.py` draws the same line for TLS.
DEPLOYED_ENVIRONMENTS = frozenset({"staging", "production"})
# Well under the 30 second request timeout, which sits inside this middleware and so cannot
# bound this call.
REDIS_TIMEOUT_SECONDS = 2
UNKNOWN_CLIENT_ADDRESS = "unknown"
GLOBAL_BUCKET_PREFIX = "ratelimit:global"
AUTH_BUCKET_PREFIX = "ratelimit:auth"
# Increment and arm the expiry in one server-side operation. The expiry is set whenever the key
# has none (TTL below zero), so a window runs from its first request rather than being pushed
# forward by every later one, which would lock out a steady client permanently.
INCREMENT_WITHIN_WINDOW = """
local current = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""

logger = structlog.get_logger(__name__)


class MissingRedisUrlError(RedisError):
    """A deployed environment reached the limiter with no REDIS_URL configured."""


class RateLimitMiddleware:
    """Pure ASGI middleware counting each client's requests against two buckets."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        """Wrap the app and record how this environment counts and what it does without Redis."""
        self.app = app
        self.is_deployed = settings.environment in DEPLOYED_ENVIRONMENTS
        self.redis_url = settings.redis_url.get_secret_value() if settings.redis_url else None
        self.redis_client: redis_asyncio.Redis | None = None
        # Per instance, never module level: the suite builds an application per test and makes far
        # more than the global limit of requests from one address in a single process.
        self.in_memory_windows: dict[str, tuple[int, float]] = {}
        self.has_logged_in_memory = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Count the request against every bucket that applies, or answer the refusal itself."""
        if scope["type"] != "http" or scope["path"] in RATE_LIMIT_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        buckets = build_buckets(scope["method"], scope["path"], read_client_address(scope))
        if self.redis_url is None and self.is_deployed:
            # Settings require REDIS_URL in production but not in staging, so this is reachable.
            # A deployed environment without Redis gets the outage behavior rather than a
            # per-replica count, which is very nearly no limit at all.
            await self.handle_unavailable(scope, receive, send, MissingRedisUrlError())
            return
        try:
            retry_after_seconds = await self.find_exceeded_bucket(buckets)
        except (RedisError, OSError) as err:
            await self.handle_unavailable(scope, receive, send, err)
            return
        if retry_after_seconds is None:
            await self.app(scope, receive, send)
            return
        await send_error_envelope(
            send,
            429,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            RATE_LIMIT_EXCEEDED_MESSAGE,
            headers={"Retry-After": str(retry_after_seconds)},
        )

    async def find_exceeded_bucket(self, buckets: list[tuple[str, int]]) -> int | None:
        """Return the seconds to wait when a bucket is over its limit, or None when none is."""
        for key, limit in buckets:
            count, ttl_seconds = await self.increment(key)
            if count > limit:
                return ttl_seconds
        return None

    async def increment(self, key: str) -> tuple[int, int]:
        """Return this key's count and the seconds left in its window, after counting one more."""
        if self.redis_url is None:
            self.log_in_memory_once()
            return self.increment_in_memory(key)
        if self.redis_client is None:
            # `from_url` carries no annotations in redis-py, so the constructor is used
            # instead and the URL is parsed by the same helper the library uses itself.
            # Both timeouts are mandatory (R-346). redis-py defaults them to None, and this
            # middleware is registered outside RequestTimeoutMiddleware, so nothing else bounds
            # the call: a Redis that holds the connection open and stops answering, which is what
            # a failover or a partition without a reset looks like, would hang every non-exempt
            # route forever rather than costing the four auth paths. `TimeoutError` from redis-py
            # subclasses `RedisError`, so it lands in the same handler as any other failure.
            self.redis_client = redis_asyncio.Redis.from_url(
                self.redis_url,
                socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
                socket_timeout=REDIS_TIMEOUT_SECONDS,
            )
        # redis-py types `eval` as possibly synchronous because the sync and async clients share
        # the command mixin; the async client always returns an awaitable here.
        result = cast(
            "Awaitable[list[int]]",
            self.redis_client.eval(INCREMENT_WITHIN_WINDOW, 1, key, str(RATE_LIMIT_WINDOW_SECONDS)),
        )
        count, ttl_seconds = await result
        return int(count), normalize_retry_after(int(ttl_seconds))

    def increment_in_memory(self, key: str) -> tuple[int, int]:
        """Count one request in this process, starting a new window when the last one expired."""
        now = time.monotonic()
        self.forget_expired_windows(now)
        count, window_started_at = self.in_memory_windows.get(key, (0, now))
        if now - window_started_at >= RATE_LIMIT_WINDOW_SECONDS:
            count, window_started_at = 0, now
        count += 1
        self.in_memory_windows[key] = (count, window_started_at)
        elapsed = int(now - window_started_at)
        return count, normalize_retry_after(RATE_LIMIT_WINDOW_SECONDS - elapsed)

    def forget_expired_windows(self, now: float) -> None:
        """Drop windows that have already closed, so the map cannot grow without bound.

        One entry exists per client address per bucket, and the address comes from the network, so
        a process that never evicted would grow with every distinct source it ever saw. An entry
        is only useful until its window closes.
        """
        expired = [
            key
            for key, (_count, started_at) in self.in_memory_windows.items()
            if now - started_at >= RATE_LIMIT_WINDOW_SECONDS
        ]
        for key in expired:
            del self.in_memory_windows[key]

    def log_in_memory_once(self) -> None:
        """Say once per process that this instance is counting locally rather than in Redis."""
        if self.has_logged_in_memory:
            return
        self.has_logged_in_memory = True
        logger.warning("rate_limiter_in_memory")

    async def handle_unavailable(
        self, scope: Scope, receive: Receive, send: Send, err: Exception
    ) -> None:
        """Fail the auth paths closed in production, and count locally everywhere else."""
        logger.error("rate_limiter_unavailable", error_type=type(err).__name__, path=scope["path"])
        if not self.is_deployed:
            # The client is kept rather than discarded: redis-py's pool reconnects by itself on
            # the next command, and dropping the object leaked its open sockets once per failed
            # request for as long as the outage lasted.
            self.log_in_memory_once()
            await self.serve_or_refuse_from_memory(scope, receive, send)
            return
        if counts_against_auth_bucket(scope["method"], scope["path"]):
            await send_error_envelope(
                send,
                503,
                ErrorCode.SERVER_RATE_LIMIT_UNAVAILABLE,
                RATE_LIMIT_UNAVAILABLE_MESSAGE,
            )
            return
        await self.app(scope, receive, send)

    async def serve_or_refuse_from_memory(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Outside production only, keep limiting from the in-process counter."""
        buckets = build_buckets(scope["method"], scope["path"], read_client_address(scope))
        retry_after_seconds = None
        for key, limit in buckets:
            count, ttl_seconds = self.increment_in_memory(key)
            if count > limit:
                retry_after_seconds = ttl_seconds
                break
        if retry_after_seconds is None:
            await self.app(scope, receive, send)
            return
        await send_error_envelope(
            send,
            429,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            RATE_LIMIT_EXCEEDED_MESSAGE,
            headers={"Retry-After": str(retry_after_seconds)},
        )


def counts_against_auth_bucket(method: str, path: str) -> bool:
    """Return true when this request handles credentials, by its path or by its method."""
    return path in AUTH_RATE_LIMITED_PATHS or (method, path) in AUTH_RATE_LIMITED_ROUTES


def build_buckets(method: str, path: str, client_address: str) -> list[tuple[str, int]]:
    """Return the key and limit of every bucket this request counts against, global first."""
    buckets = [(f"{GLOBAL_BUCKET_PREFIX}:{client_address}", GLOBAL_REQUEST_LIMIT)]
    if counts_against_auth_bucket(method, path):
        buckets.append((f"{AUTH_BUCKET_PREFIX}:{client_address}", AUTH_REQUEST_LIMIT))
    return buckets


def read_client_address(scope: Scope) -> str:
    """Return the address uvicorn resolved for this client, never a header this module parsed."""
    client = scope.get("client")
    return client[0] if client else UNKNOWN_CLIENT_ADDRESS


def normalize_retry_after(ttl_seconds: int) -> int:
    """Return a positive Retry-After, falling back to the window when the key reports no expiry."""
    if ttl_seconds <= 0:
        return RATE_LIMIT_WINDOW_SECONDS
    return ttl_seconds
