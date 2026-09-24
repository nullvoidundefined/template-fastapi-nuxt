"""B-24 and B-30 for the auth routes: what PostHog and Sentry receive about a signed-in person.

B-24: registering, signing in, signing out, and changing a password each send one server event to
PostHog, named from the registry, whose distinct ID is the user's ID, and no event carries the
email address. The password-reset events join these when the reset routes exist; this base has
none, so the four events above are the whole set here.

B-30: an unhandled error in a signed-in request reaches Sentry with the user's ID and never the
email.

PostHog and Sentry are each replaced at their SDK boundary, a recorder in place of the
`posthog.Posthog` instance and a recording transport in place of Sentry's, so the application's
own clients, dependencies, and routes all run as `create_app()` assembled them.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi import APIRouter
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

REGISTER_PATH = "/v1/auth/register"
LOGIN_PATH = "/v1/auth/login"
LOGOUT_PATH = "/v1/auth/logout"
ME_PATH = "/v1/auth/me"
FAILING_PATH = "/test-only/signed-in-failure"
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
NEW_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))
TEST_DSN = "".join(("https://", "publickey", "@", "sentry.example.test", "/1"))


class RecordingPosthog:
    """Stands in for `posthog.Posthog`, recording each capture it is handed."""

    def __init__(self) -> None:
        """Start with no captures."""
        self.captures: list[dict[str, Any]] = []

    def capture(self, event: str, **kwargs: object) -> None:
        """Record the event name and every keyword the client passed."""
        self.captures.append({"event": event, **kwargs})


class RecordingTransport(Transport):
    """Records every event envelope the Sentry SDK would have sent."""

    def __init__(self) -> None:
        """Start with no events."""
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        """Keep the event carried by the envelope, if any."""
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture
def inert_sentry() -> Iterator[None]:
    """Leave the process with no active Sentry client, whatever the test initialized."""
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.init()


@pytest.mark.integration
async def test_b24_each_auth_action_sends_one_event_keyed_by_user_id_and_never_the_email(
    build_auth_app, open_auth_browsers, auth_emails
) -> None:
    """Register, sign out, sign in, change password: four events, the user's ID, no address."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    application = build_auth_app()
    recorder = RecordingPosthog()
    application.state.analytics_client = AnalyticsClient(recorder)
    email = auth_emails("analytics")

    async with open_auth_browsers(application) as [browser]:
        registered = await browser.post(
            REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
        )
        assert registered.status_code == 201, registered.text
        user_id = registered.json()["data"]["id"]
        assert (await browser.post(LOGOUT_PATH)).status_code == 204
        signed_in = await browser.post(
            LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD}
        )
        assert signed_in.status_code == 200, signed_in.text
        changed = await browser.patch(
            ME_PATH, json={"current_password": VALID_PASSWORD, "new_password": NEW_PASSWORD}
        )
        assert changed.status_code == 200, changed.text

    assert [capture["event"] for capture in recorder.captures] == [
        "user_registered",
        "user_signed_out",
        "user_signed_in",
        "user_password_changed",
    ]
    assert {capture["distinct_id"] for capture in recorder.captures} == {user_id}
    serialized_captures = json.dumps(recorder.captures).lower()
    assert email.lower() not in serialized_captures
    assert "@" not in serialized_captures


@pytest.mark.integration
async def test_b24_a_refused_login_sends_no_event(
    build_auth_app, open_auth_browsers, auth_emails, auth_db
) -> None:
    """Only a completed action is an event: a wrong password records nothing."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415

    application = build_auth_app()
    recorder = RecordingPosthog()
    application.state.analytics_client = AnalyticsClient(recorder)
    email = auth_emails("refused")
    await auth_db.seed_user(email, VALID_PASSWORD)

    async with open_auth_browsers(application) as [browser]:
        refused = await browser.post(LOGIN_PATH, json={"email": email, "password": NEW_PASSWORD})

    assert refused.status_code == 401, refused.text
    assert recorder.captures == []


@pytest.mark.integration
@pytest.mark.usefixtures("inert_sentry")
async def test_b30_an_unhandled_error_in_a_signed_in_request_carries_the_user_id_only(
    build_auth_app, open_auth_browsers, auth_emails, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Sentry event names the user by ID, and the email appears nowhere in it."""
    from app.dependencies.current_user import CurrentUser  # noqa: PLC0415

    monkeypatch.setenv("SENTRY_DSN", TEST_DSN)
    application = build_auth_app()
    failing_router = APIRouter()

    @failing_router.get(FAILING_PATH)
    async def fail_for_signed_in_user(current: CurrentUser) -> None:
        raise RuntimeError("unexpected failure for a signed-in user")

    application.include_router(failing_router)
    transport = RecordingTransport()
    sentry_sdk.get_client().transport = transport
    email = auth_emails("reported")

    async with open_auth_browsers(application) as [browser]:
        registered = await browser.post(
            REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
        )
        assert registered.status_code == 201, registered.text
        response = await browser.get(FAILING_PATH)

    assert response.status_code == 500
    runtime_error_events = [
        event
        for event in transport.events
        if event.get("exception", {}).get("values", [{}])[-1].get("type") == "RuntimeError"
    ]
    assert len(runtime_error_events) == 1, transport.events
    [event] = runtime_error_events
    assert event.get("user") == {"id": registered.json()["data"]["id"]}
    assert event.get("tags", {}).get("request_id") == response.headers["X-Request-Id"]
    assert email.lower() not in json.dumps(event, default=str).lower()
