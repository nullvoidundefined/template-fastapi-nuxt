"""Sends server-side analytics events to PostHog; the only module that imports the SDK (R-343).

An event is keyed by the user's ID and carries the request ID, and nothing else about the person:
`track_event` takes a UUID rather than a free-form distinct ID, so an email address cannot be
passed as one by accident (B-24, R-104).

The SDK queues each event and uploads it from its own thread, so a capture is cheap; it still runs
in a worker thread inside `with_client_telemetry`, which logs it and bounds it with a timeout. The
upload itself happens later on the SDK's thread, outside that wrapper, so the SDK's `on_error`
callback logs a failed upload as a failed `upload` call with the batch size (R-346). A
PostHog failure is logged and swallowed here, because a lost analytics row must never fail the
sign-in that produced it (spec, failure modes). Without `POSTHOG_API_KEY` the factory logs one
warning and returns a client whose every event is a no-op.
"""

import asyncio
import uuid
from collections.abc import Mapping
from typing import Protocol

import structlog
from posthog import Posthog

from app.analytics.events import AnalyticsEvent
from app.clients.telemetry import REQUEST_ID_HEADER, with_client_telemetry
from app.core.settings import Settings

POSTHOG_PROVIDER = "posthog"
CAPTURE_OPERATION = "capture"
UPLOAD_OPERATION = "upload"
# Bounds both the SDK's own upload requests and the enqueue the wrapper times.
POSTHOG_TIMEOUT_SECONDS = 5.0
# The SDK's own retries of a failed batch upload, each after an exponential backoff.
POSTHOG_MAX_RETRIES = 3

# How long shutdown waits for PostHog to flush its queue before giving up on it.
ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS = 5.0

logger = structlog.get_logger(__name__)


class PosthogCapture(Protocol):
    """The one SDK method this client calls."""

    def capture(self, event: str, **kwargs: object) -> object:
        """Queue one event for upload."""


class AnalyticsClient:
    """Tracks registry events for a user, or does nothing when no SDK client was configured."""

    def __init__(self, posthog: PosthogCapture | None) -> None:
        """Hold the SDK client, or None for the disabled no-op."""
        self.posthog = posthog

    @property
    def is_enabled(self) -> bool:
        """Return True when events are actually sent."""
        return self.posthog is not None

    async def track_event(self, user_id: uuid.UUID, event: AnalyticsEvent) -> None:
        """Send one event keyed by the user's ID; log and continue when PostHog fails."""
        posthog = self.posthog
        if posthog is None:
            return

        async def capture(forwarded_headers: Mapping[str, str]) -> None:
            properties = build_event_properties(forwarded_headers)
            await asyncio.to_thread(
                posthog.capture, event.value, distinct_id=str(user_id), properties=properties
            )

        try:
            await with_client_telemetry(
                POSTHOG_PROVIDER, CAPTURE_OPERATION, capture, POSTHOG_TIMEOUT_SECONDS
            )
        # Broad on purpose: analytics must never be the reason a request fails (R-344 still holds,
        # since the error is logged with its cause). Every failure is caught and reported alike.
        except Exception as err:  # noqa: BLE001
            logger.warning("analytics_capture_failed", analytics_event=event.value, exc_info=err)

    async def close(self) -> None:
        """Flush queued events and stop the SDK, giving up after a bounded wait.

        A PostHog outage makes the SDK's flush retry for a long time, and shutdown must not wait
        for it: the process is being replaced, and a few lost events cost less than a stuck deploy.
        """
        shutdown = getattr(self.posthog, "shutdown", None)
        if shutdown is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(shutdown), timeout=ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS
            )
        except TimeoutError:
            logger.warning(
                "analytics_shutdown_timed_out", timeout_seconds=ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS
            )


def build_event_properties(forwarded_headers: Mapping[str, str]) -> dict[str, object]:
    """Return the event's properties: the request ID when one is bound, and nothing else."""
    request_id = forwarded_headers.get(REQUEST_ID_HEADER)
    return {"request_id": request_id} if request_id else {}


def create_analytics_client(settings: Settings) -> AnalyticsClient:
    """Build the PostHog client from settings, or the no-op with one warning when unkeyed."""
    if settings.posthog_api_key is None or not settings.posthog_api_key.get_secret_value():
        logger.warning("analytics_disabled", reason="POSTHOG_API_KEY is not set")
        return AnalyticsClient(None)
    posthog = Posthog(
        settings.posthog_api_key.get_secret_value(),
        host=settings.posthog_host,
        timeout=POSTHOG_TIMEOUT_SECONDS,
        max_retries=POSTHOG_MAX_RETRIES,
        disable_geoip=True,
        on_error=log_upload_failure,
    )
    return AnalyticsClient(posthog)


def log_upload_failure(err: Exception, batch: list[object]) -> None:
    """Log a batch upload the SDK gave up on, from its consumer thread, as a failed client call."""
    logger.warning(
        "client_call_failed",
        provider=POSTHOG_PROVIDER,
        operation=UPLOAD_OPERATION,
        outcome="failure",
        batch_size=len(batch),
        exc_info=err,
    )
