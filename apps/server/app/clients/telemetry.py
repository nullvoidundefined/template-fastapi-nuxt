"""Wraps every outbound provider call in one log line, a timeout, and the request ID (R-346).

A client hands this its call rather than instrumenting itself, so no client can ship without the
duration and outcome being logged and no call can run without a deadline. The call receives the
headers to forward: the request ID when one is bound, so the provider's own logs can be joined to
ours, and nothing when the call comes from a job with no request in flight.

The one broad `except Exception` in the application is here, and it re-raises. Swallowing would
turn a provider failure into a silent success, which for the reset email means a lost message.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

import structlog

REQUEST_ID_HEADER = "X-Request-Id"
MILLISECONDS_PER_SECOND = 1000

logger = structlog.get_logger(__name__)


async def with_client_telemetry[T](
    provider: str,
    operation: str,
    call: Callable[[Mapping[str, str]], Awaitable[T]],
    timeout_seconds: float,
) -> T:
    """Run the call within the timeout, log its provider, duration, and outcome, and re-raise."""
    started_at = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await call(build_forwarded_headers())
    except Exception as err:
        logger.warning(
            "client_call_failed",
            provider=provider,
            operation=operation,
            duration_ms=measure_elapsed_ms(started_at),
            outcome="failure",
            exc_info=err,
        )
        raise
    logger.info(
        "client_call_succeeded",
        provider=provider,
        operation=operation,
        duration_ms=measure_elapsed_ms(started_at),
        outcome="success",
    )
    return result


def build_forwarded_headers() -> dict[str, str]:
    """Return the request ID header when one is bound to this context, and nothing otherwise."""
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    return {REQUEST_ID_HEADER: str(request_id)} if request_id else {}


def measure_elapsed_ms(started_at: float) -> float:
    """Return the milliseconds since `started_at`, rounded for a log line."""
    return round((time.perf_counter() - started_at) * MILLISECONDS_PER_SECOND, 2)
