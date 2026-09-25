"""B-24 unit tests for the PostHog client in app/clients/analytics.py and the event registry.

The client is the only module that talks to the PostHog SDK. It owes four things: the event name
comes from the registry and never from a literal, the distinct ID is the user's ID and nothing else
identifies the person, the request ID travels with the event so an analytics row can be joined to
the logs, and a provider failure is logged without ever failing the request that emitted it.
Without a key the client logs one warning when it is built and every event is a quiet no-op.

The SDK is replaced by a recorder at its own boundary, so what is asserted is exactly what the SDK
would have been handed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

if TYPE_CHECKING:
    from app.core.settings import Settings

USER_ID = uuid.UUID("5f0b1f9c-3a4e-4c1d-9a51-0d2f6c7e8a10")
REQUEST_ID = "req-analytics-1"


class RecordingPosthog:
    """Stands in for `posthog.Posthog`, recording each capture it is handed."""

    def __init__(self) -> None:
        """Start with no captures."""
        self.captures: list[dict[str, object]] = []

    def capture(self, event: str, **kwargs: object) -> None:
        """Record the event name and every keyword the client passed."""
        self.captures.append({"event": event, **kwargs})


class RefusingPosthog:
    """Stands in for a PostHog SDK whose queue or network raises."""

    def capture(self, event: str, **kwargs: object) -> None:
        """Raise the error a full queue or a dead socket surfaces as."""
        raise OSError("posthog unreachable")


class BrokenPosthog:
    """Stands in for an SDK failing in a way nobody anticipated, and records its shutdown."""

    def __init__(self) -> None:
        """Start running."""
        self.is_shut_down = False

    def capture(self, event: str, **kwargs: object) -> None:
        """Raise an error outside the anticipated network and value errors."""
        raise RuntimeError("posthog internal failure")

    def shutdown(self) -> None:
        """Record that queued events were flushed and the SDK stopped."""
        self.is_shut_down = True


async def test_b24_an_unanticipated_sdk_error_is_logged_and_never_fails_the_request() -> None:
    """Analytics is never a reason a sign-in fails, whatever the SDK raises."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    with structlog.testing.capture_logs() as logs:
        try:
            await AnalyticsClient(BrokenPosthog()).track_event(
                USER_ID, AnalyticsEvent.USER_SIGNED_IN
            )
        except RuntimeError as err:
            raise AssertionError("an analytics failure escaped into the request") from err

    assert "analytics_capture_failed" in [log["event"] for log in logs]


async def test_b24_closing_the_client_flushes_and_stops_the_sdk() -> None:
    """Queued events are sent before the process exits, so a deploy does not drop them."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    posthog = BrokenPosthog()
    analytics_client = AnalyticsClient(posthog)

    assert hasattr(analytics_client, "close"), "the client has no way to flush on shutdown"
    await analytics_client.close()

    assert posthog.is_shut_down


class HangingPosthog:
    """Stands in for an SDK whose flush never returns, as it does against a dead endpoint."""

    def capture(self, event: str, **kwargs: object) -> None:
        """Accept the event."""

    def shutdown(self) -> None:
        """Block well past any shutdown budget."""
        import time  # noqa: PLC0415

        time.sleep(30)


async def test_b24_closing_a_hung_client_gives_up_within_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PostHog outage cannot hold the process open at shutdown."""
    import time  # noqa: PLC0415

    from app.clients import analytics as analytics_module  # noqa: PLC0415
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    monkeypatch.setattr(analytics_module, "ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS", 0.2, raising=False)
    started_at = time.perf_counter()

    with structlog.testing.capture_logs() as logs:
        await AnalyticsClient(HangingPosthog()).close()

    assert time.perf_counter() - started_at < 2
    assert "analytics_shutdown_timed_out" in [log["event"] for log in logs]


async def test_b24_the_api_lifespan_closes_the_analytics_client_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutting the API down flushes PostHog's queue."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415
    from app.core.settings import get_settings  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://127.0.0.1:1/none")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    application = create_app()
    posthog = BrokenPosthog()
    application.state.analytics_client = AnalyticsClient(posthog)

    async with application.router.lifespan_context(application):
        assert not posthog.is_shut_down

    assert posthog.is_shut_down
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def empty_structlog_context() -> Iterator[None]:
    """Start and end every test with no bound request ID."""
    clear_contextvars()
    yield
    clear_contextvars()


def build_settings(**overrides: str) -> Settings:
    """Build Settings with a database URL, so the constructor has what it requires."""
    from app.core.settings import Settings  # noqa: PLC0415

    return Settings(
        database_url="postgresql+asyncpg://127.0.0.1:1/none",
        **overrides,  # type: ignore[arg-type]  # pydantic-settings' __init__ stub types its
        # own config kwargs (_case_sensitive, _env_file, ...), not the model fields **overrides
        # forwards, so mypy checks the spread against every one of those instead.
    )


def test_b24_the_registry_names_the_four_auth_events_as_object_action() -> None:
    """The four auth events this base carries are registered, each value snake_case past tense."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415

    assert {event.value for event in AnalyticsEvent} >= {
        "user_registered",
        "user_signed_in",
        "user_signed_out",
        "user_password_changed",
    }


async def test_b24_an_event_carries_the_user_id_as_distinct_id_and_the_request_id() -> None:
    """The SDK receives the registry value, the user's ID, and the bound request ID."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    recorder = RecordingPosthog()
    bind_contextvars(request_id=REQUEST_ID)

    await AnalyticsClient(recorder).track_event(USER_ID, AnalyticsEvent.USER_SIGNED_IN)

    assert recorder.captures == [
        {
            "event": "user_signed_in",
            "distinct_id": str(USER_ID),
            "properties": {"request_id": REQUEST_ID},
        }
    ]


async def test_b23_an_event_is_logged_as_a_posthog_client_call() -> None:
    """The capture goes through the telemetry wrapper, so it logs provider and outcome."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        await AnalyticsClient(RecordingPosthog()).track_event(
            USER_ID, AnalyticsEvent.USER_REGISTERED
        )

    [call_event] = [event for event in captured_events if event.get("provider") == "posthog"]
    assert call_event["operation"] == "capture"
    assert call_event["outcome"] == "success"


async def test_b24_a_provider_failure_is_logged_and_never_raised() -> None:
    """A PostHog outage costs an analytics row, never the request that emitted it."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        await AnalyticsClient(RefusingPosthog()).track_event(
            USER_ID, AnalyticsEvent.USER_SIGNED_OUT
        )

    failure_names = [event["event"] for event in captured_events]
    assert "analytics_capture_failed" in failure_names


async def test_b24_without_a_key_the_client_warns_once_and_every_event_is_a_no_op() -> None:
    """An unconfigured client is built with one warning and then tracks nothing, silently."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients.analytics import create_analytics_client  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        client = create_analytics_client(build_settings())
        await client.track_event(USER_ID, AnalyticsEvent.USER_SIGNED_IN)
        await client.track_event(USER_ID, AnalyticsEvent.USER_SIGNED_OUT)

    assert client.is_enabled is False
    assert [event["event"] for event in captured_events] == ["analytics_disabled"]


def test_b24_with_a_key_the_client_is_enabled() -> None:
    """A configured key builds a client that sends, rather than the no-op."""
    from app.clients.analytics import create_analytics_client  # noqa: PLC0415

    project_key = "_".join(("phc", "unit", "test"))
    client = create_analytics_client(build_settings(posthog_api_key=project_key))

    assert client.is_enabled is True
