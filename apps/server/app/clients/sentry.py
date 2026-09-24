"""Initializes Sentry error reporting and decides what an event may carry (B-30).

Sentry starts only when `SENTRY_DSN` is set; without it the process logs one warning and the SDK
stays inert, so every `set_tag` and `set_user` call below is a free no-op. The FastAPI and
Starlette integrations, which the SDK enables on its own when it finds FastAPI installed, report
an unhandled exception from the outermost layer after the 500 handler has answered.

An event is identified by the request ID tag and the user's ID, never the email (R-104).
`send_default_pii` and frame locals stay off, and `scrub_sentry_event` removes cookies, the
Authorization header, and every user field other than the ID before an event leaves the process,
so a later change to what the SDK collects cannot leak a session token.
"""

from typing import Any, cast

import sentry_sdk
import structlog
from sentry_sdk.types import Event, Hint

from app.core.settings import Settings

REQUEST_ID_TAG = "request_id"
SCRUBBED_HEADER_NAMES = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization"})
KEPT_USER_FIELDS = frozenset({"id"})

logger = structlog.get_logger(__name__)


def initialize_sentry(settings: Settings) -> bool:
    """Start the SDK when a DSN is configured, returning whether it started."""
    if settings.sentry_dsn is None or not settings.sentry_dsn.get_secret_value():
        logger.warning("error_reporting_disabled", reason="SENTRY_DSN is not set")
        # Replaces any client an earlier application in this process started, so an application
        # built without a DSN never reports through someone else's configuration.
        sentry_sdk.get_global_scope().set_client(None)
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        # Frame locals include the raw ASGI scope, whose headers carry the session cookie and any
        # Authorization value verbatim; the end-to-end test of this client caught exactly that.
        include_local_variables=False,
        before_send=scrub_sentry_event,
    )
    return True


def scrub_sentry_event(event: Event, hint: Hint) -> Event | None:
    """Remove cookies, credential headers, and every user field but the ID from the event."""
    request = cast(dict[str, Any] | None, event.get("request"))
    if request is not None:
        request.pop("cookies", None)
        # The body of a failing login or registration carries the email, and a reset link's query
        # string carries its token, so neither the body nor any query string leaves the process.
        request.pop("data", None)
        request.pop("query_string", None)
        if isinstance(request.get("url"), str):
            request["url"] = strip_query_string(request["url"])
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: value
                for name, value in headers.items()
                if name.lower() not in SCRUBBED_HEADER_NAMES
            }
    strip_breadcrumb_queries(event)
    user = cast(dict[str, Any] | None, event.get("user"))
    if user is not None:
        event["user"] = {name: value for name, value in user.items() if name in KEPT_USER_FIELDS}
    return event


def strip_query_string(url: str) -> str:
    """Return the URL with everything from its first `?` or `#` removed."""
    return url.split("?", 1)[0].split("#", 1)[0]


def strip_breadcrumb_queries(event: Event) -> None:
    """Remove the query string from every string value a breadcrumb's data carries."""
    breadcrumbs = cast(dict[str, Any] | None, event.get("breadcrumbs"))
    for breadcrumb in (breadcrumbs or {}).get("values", []):
        data = breadcrumb.get("data")
        if isinstance(data, dict):
            breadcrumb["data"] = {
                name: strip_query_string(value) if isinstance(value, str) else value
                for name, value in data.items()
            }


def tag_sentry_request(request_id: str | None) -> None:
    """Tag every event raised in this request's scope with its request ID."""
    if request_id:
        sentry_sdk.set_tag(REQUEST_ID_TAG, request_id)


def identify_sentry_user(user_id: str) -> None:
    """Name the signed-in user on this request's events by ID only."""
    sentry_sdk.set_user({"id": user_id})
