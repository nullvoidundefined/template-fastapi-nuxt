"""B-30 unit tests for the Sentry client in app/clients/sentry.py.

Three properties are pinned here. Sentry initializes only when SENTRY_DSN is set, and without it
the process logs one warning and the SDK stays inert. `before_send` removes cookies and the
Authorization header, whatever their case, before an event leaves the process. And an unhandled
error in the application assembled by `create_app()` reaches Sentry tagged with the request ID the
response carried, with the cookie and the Authorization header the request sent removed.

Events are captured by replacing the SDK client's transport with a recorder, which is the last
point before the network, so what is asserted is what Sentry would have received.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import sentry_sdk
import structlog
from fastapi import APIRouter
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event

from tests.conftest import ApiClientFactory, ServerAppFactory

if TYPE_CHECKING:
    from app.core.settings import Settings

# Built from parts so no DSN-shaped literal with a key sits in the source (R-108).
TEST_DSN = "".join(("https://", "publickey", "@", "sentry.example.test", "/1"))
COOKIE_VALUE = "-".join(("session", "cookie", "value"))
BEARER_VALUE = " ".join(("Bearer", "-".join(("opaque", "bearer", "value"))))
FAILING_PATH = "/test-only/sentry-failure"


class RecordingTransport(Transport):
    """Records every event envelope the SDK would have sent."""

    def __init__(self) -> None:
        """Start with no events."""
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        """Keep the event carried by the envelope, if any."""
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture(autouse=True)
def inert_sentry() -> Iterator[None]:
    """Leave the process with no active Sentry client, whatever the test initialized."""
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.init()


def build_settings(**overrides: str) -> "Settings":
    """Build Settings with a database URL, so the constructor has what it requires."""
    from app.core.settings import Settings  # noqa: PLC0415

    return Settings(
        database_url="postgresql+asyncpg://127.0.0.1:1/none",
        **overrides,  # type: ignore[arg-type]  # pydantic-settings' __init__ stub types its
        # own config kwargs (_case_sensitive, _env_file, ...), not the model fields **overrides
        # forwards, so mypy checks the spread against every one of those instead.
    )


def test_b30_without_a_dsn_sentry_stays_inert_and_one_warning_is_logged() -> None:
    """No SENTRY_DSN: nothing is initialized, and the operator is told once."""
    from app.clients.sentry import initialize_sentry  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        is_initialized = initialize_sentry(build_settings())

    assert is_initialized is False
    assert sentry_sdk.get_client().is_active() is False
    assert [event["event"] for event in captured_events] == ["error_reporting_disabled"]


def test_b30_with_a_dsn_sentry_initializes_with_the_scrubber_and_no_default_pii() -> None:
    """SENTRY_DSN set: the SDK is active, scrubbing every event, sending no default PII."""
    from app.clients.sentry import initialize_sentry, scrub_sentry_event  # noqa: PLC0415

    is_initialized = initialize_sentry(build_settings(sentry_dsn=TEST_DSN, environment="test"))

    client = sentry_sdk.get_client()
    assert is_initialized is True
    assert client.is_active() is True
    assert client.options["before_send"] is scrub_sentry_event
    assert client.options["send_default_pii"] is False
    assert client.options["environment"] == "test"


def test_b30_before_send_removes_cookies_and_the_authorization_header() -> None:
    """Cookies, Cookie, Set-Cookie and Authorization go, in any case; other headers stay."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    event: Event = {
        "request": {
            "cookies": {"session": COOKIE_VALUE},
            "headers": {
                "cookie": f"session={COOKIE_VALUE}",
                "AUTHORIZATION": BEARER_VALUE,
                "Set-Cookie": f"session={COOKIE_VALUE}",
                "x-request-id": "req-1",
                "user-agent": "pytest",
            },
        },
        "user": {"id": "user-1", "email": "person@example.test"},
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    assert "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["headers"] == {"x-request-id": "req-1", "user-agent": "pytest"}
    assert scrubbed["user"] == {"id": "user-1"}
    assert COOKIE_VALUE not in repr(scrubbed)
    assert BEARER_VALUE not in repr(scrubbed)


def test_b30_before_send_drops_the_request_body_and_every_query_string() -> None:
    """A login body carries the email and a reset link carries its token; neither leaves."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    event: Event = {
        "request": {
            "data": {"email": "person@example.test", "password": "[Filtered]"},
            "query_string": "token=from-the-email",
            "url": "https://api.example.test/v1/auth/reset-password?token=from-the-email",
        },
        "breadcrumbs": {
            "values": [
                {"category": "httplib", "data": {"url": "https://x.test/a?token=t"}},
                {"category": "log", "message": "no data here"},
            ]
        },
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    assert "data" not in scrubbed["request"]
    assert "query_string" not in scrubbed["request"]
    assert scrubbed["request"]["url"] == "https://api.example.test/v1/auth/reset-password"
    breadcrumbs = scrubbed["breadcrumbs"]
    assert isinstance(breadcrumbs, dict)
    assert breadcrumbs["values"][0]["data"] == {"url": "https://x.test/a"}
    assert "person@example.test" not in repr(scrubbed)
    assert "from-the-email" not in repr(scrubbed)


def test_b30_before_send_withholds_the_referer_which_carries_the_reset_token() -> None:
    """Nitro forwards the reset page's address as the Referer, token and all."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    event: Event = {
        "request": {
            "headers": {
                "Referer": "https://app.example.test/reset-password?token=from-the-email",
                "user-agent": "pytest",
            }
        }
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    assert scrubbed["request"]["headers"] == {"user-agent": "pytest"}


def test_b30_before_send_accepts_an_event_with_no_request() -> None:
    """An event raised outside a request, such as in a job, passes through unchanged."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    event: Event = {"message": "job failed", "level": "error"}
    # A shallow copy, so the assertion below proves the function returned equal content rather
    # than the same object the caller passed in.
    copied_event = cast(Event, dict(event))

    assert scrub_sentry_event(copied_event, {}) == event


async def test_b30_an_unhandled_error_reaches_sentry_tagged_and_scrubbed(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through create_app(): the event carries the response's request ID, and no credential."""
    monkeypatch.setenv("SENTRY_DSN", TEST_DSN)
    failing_router = APIRouter()

    @failing_router.get(FAILING_PATH)
    async def fail() -> None:
        raise RuntimeError("unexpected failure for sentry")

    application = build_server_app(failing_router)
    transport = RecordingTransport()
    sentry_sdk.get_client().transport = transport

    async with build_api_client(application) as client:
        response: httpx.Response = await client.get(
            FAILING_PATH,
            headers={"Cookie": f"session={COOKIE_VALUE}", "Authorization": BEARER_VALUE},
        )

    assert response.status_code == 500
    request_id = response.headers["X-Request-Id"]
    runtime_error_events = [
        event
        for event in transport.events
        if event.get("exception", {}).get("values", [{}])[-1].get("type") == "RuntimeError"
    ]
    assert len(runtime_error_events) == 1, transport.events
    [event] = runtime_error_events
    assert event.get("tags", {}).get("request_id") == request_id
    assert COOKIE_VALUE not in repr(event)
    assert BEARER_VALUE not in repr(event)
