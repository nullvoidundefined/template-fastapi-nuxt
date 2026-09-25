"""IAN-344 unit test: a failed PostHog background upload is logged as a failed client call.

`track_event` only enqueues; the SDK uploads the batch later from its own thread, outside
`with_client_telemetry`. The real SDK is pointed at a closed local port, so its real upload fails
and the failure has to surface through the `on_error` callback the factory wires (R-346).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import structlog

if TYPE_CHECKING:
    from app.core.settings import Settings

USER_ID = uuid.UUID("5f0b1f9c-3a4e-4c1d-9a51-0d2f6c7e8a10")
CLOSED_LOCAL_HOST = "http://127.0.0.1:1"


def build_settings(**overrides: str) -> Settings:
    """Build Settings with a database URL, so the constructor has what it requires."""
    from app.core.settings import Settings  # noqa: PLC0415

    return Settings(
        database_url="postgresql+asyncpg://127.0.0.1:1/none",
        **overrides,  # type: ignore[arg-type]  # pydantic-settings' __init__ stub types its
        # own config kwargs (_case_sensitive, _env_file, ...), not the model fields **overrides
        # forwards, so mypy checks the spread against every one of those instead.
    )


async def test_ian344_a_failed_background_upload_is_logged_as_a_failed_posthog_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refused upload yields one `client_call_failed` line naming PostHog and the upload."""
    from app.analytics.events import AnalyticsEvent  # noqa: PLC0415
    from app.clients import analytics  # noqa: PLC0415

    # Retries off, so the one failure arrives without the SDK's backoff sleeps.
    monkeypatch.setattr(analytics, "POSTHOG_MAX_RETRIES", 0, raising=False)
    project_key = "_".join(("phc", "unit", "test"))
    client = analytics.create_analytics_client(
        build_settings(posthog_api_key=project_key, posthog_host=CLOSED_LOCAL_HOST)
    )

    with structlog.testing.capture_logs() as captured_events:
        await client.track_event(USER_ID, AnalyticsEvent.USER_SIGNED_IN)
        await client.close()

    upload_failures = [
        event
        for event in captured_events
        if event["event"] == "client_call_failed" and event.get("operation") == "upload"
    ]
    assert len(upload_failures) == 1, captured_events
    [upload_failure] = upload_failures
    assert upload_failure["provider"] == "posthog"
    assert upload_failure["outcome"] == "failure"
    assert upload_failure["batch_size"] == 1
    assert upload_failure["exc_info"] is not None
