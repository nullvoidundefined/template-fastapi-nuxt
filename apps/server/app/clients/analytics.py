"""Sends server-side analytics events to PostHog; the only module that imports the SDK (R-343).

An event is keyed by the user's ID and carries the request ID, and nothing else about the person:
`track_event` takes a UUID rather than a free-form distinct ID, so an email address cannot be
passed as one by accident (B-24, R-104).

The SDK queues each event and uploads it from its own thread, so a capture is cheap; it still runs
in a worker thread inside `with_client_telemetry`, which logs it and bounds it with a timeout. A
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
# Bounds both the SDK's own upload requests and the enqueue the wrapper times.
POSTHOG_TIMEOUT_SECONDS = 5.0

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
        except (OSError, TimeoutError, ValueError) as err:
            logger.warning("analytics_capture_failed", analytics_event=event.value, exc_info=err)


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
        disable_geoip=True,
    )
    return AnalyticsClient(posthog)
