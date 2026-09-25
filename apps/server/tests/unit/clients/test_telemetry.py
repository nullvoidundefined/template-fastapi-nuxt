"""R-346 unit tests for `with_client_telemetry` in app/clients/telemetry.py.

Every outbound call is wrapped once, and the wrapper owes four things: a log line naming the
provider, the operation, the duration, and the outcome; the request ID forwarded to the call when
one is bound; the caller's timeout enforced; and the original exception re-raised, never
swallowed. structlog's `capture_logs` records what the wrapper emitted.
"""

import asyncio
from collections.abc import Iterator, Mapping

import pytest
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.typing import EventDict

PROVIDER = "resend"
OPERATION = "send_email"
REQUEST_ID = "req-telemetry-1"
TIMEOUT_SECONDS = 1.0
SHORT_TIMEOUT_SECONDS = 0.01


@pytest.fixture(autouse=True)
def empty_structlog_context() -> Iterator[None]:
    """Start and end every test with no bound request ID."""
    clear_contextvars()
    yield
    clear_contextvars()


def client_call_events(captured_events: list[EventDict]) -> list[EventDict]:
    """Return only the events that name the provider under test."""
    return [event for event in captured_events if event.get("provider") == PROVIDER]


async def test_r346_a_successful_call_returns_its_result_and_logs_the_outcome() -> None:
    """The result passes through, and one line records provider, operation, duration, outcome."""
    from app.clients.telemetry import with_client_telemetry  # noqa: PLC0415

    async def answer(headers: Mapping[str, str]) -> str:
        return "delivered"

    with structlog.testing.capture_logs() as captured_events:
        result = await with_client_telemetry(PROVIDER, OPERATION, answer, TIMEOUT_SECONDS)

    assert result == "delivered"
    [event] = client_call_events(captured_events)
    assert event["operation"] == OPERATION
    assert event["outcome"] == "success"
    assert isinstance(event["duration_ms"], float)
    assert event["duration_ms"] >= 0


async def test_r346_a_failing_call_logs_the_failure_and_re_raises_the_same_error() -> None:
    """The exception reaches the caller unchanged, after a line recording the failed outcome."""
    from app.clients.telemetry import with_client_telemetry  # noqa: PLC0415

    failure = ValueError("provider refused")

    async def refuse(headers: Mapping[str, str]) -> str:
        raise failure

    with (
        structlog.testing.capture_logs() as captured_events,
        pytest.raises(ValueError, match="provider refused") as raised,
    ):
        await with_client_telemetry(PROVIDER, OPERATION, refuse, TIMEOUT_SECONDS)

    assert raised.value is failure
    [event] = client_call_events(captured_events)
    assert event["outcome"] == "failure"
    assert isinstance(event["duration_ms"], float)


async def test_r346_the_bound_request_id_is_forwarded_to_the_call() -> None:
    """A call made while a request ID is bound receives it as the X-Request-Id header."""
    from app.clients.telemetry import with_client_telemetry  # noqa: PLC0415

    received_headers: list[Mapping[str, str]] = []

    async def record(headers: Mapping[str, str]) -> None:
        received_headers.append(dict(headers))

    bind_contextvars(request_id=REQUEST_ID)
    await with_client_telemetry(PROVIDER, OPERATION, record, TIMEOUT_SECONDS)

    assert received_headers == [{"X-Request-Id": REQUEST_ID}]


async def test_r346_no_request_id_header_is_sent_when_none_is_bound() -> None:
    """A call from a job with no request in flight sends no empty or invented request ID."""
    from app.clients.telemetry import with_client_telemetry  # noqa: PLC0415

    received_headers: list[Mapping[str, str]] = []

    async def record(headers: Mapping[str, str]) -> None:
        received_headers.append(dict(headers))

    await with_client_telemetry(PROVIDER, OPERATION, record, TIMEOUT_SECONDS)

    assert received_headers == [{}]


async def test_r346_the_callers_timeout_bounds_the_call() -> None:
    """A call that outlives the timeout raises TimeoutError and is logged as a failure."""
    from app.clients.telemetry import with_client_telemetry  # noqa: PLC0415

    async def hang(headers: Mapping[str, str]) -> None:
        await asyncio.sleep(10)

    with (
        structlog.testing.capture_logs() as captured_events,
        pytest.raises(TimeoutError),
    ):
        await with_client_telemetry(PROVIDER, OPERATION, hang, SHORT_TIMEOUT_SECONDS)

    [event] = client_call_events(captured_events)
    assert event["outcome"] == "failure"
