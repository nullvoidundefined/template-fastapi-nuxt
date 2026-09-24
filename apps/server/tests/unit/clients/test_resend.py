"""B-47 and R-346 unit tests for the Resend client in app/clients/resend.py.

The client is driven through `httpx.MockTransport`, so every assertion is about the request the
client really built: the endpoint, the bearer header, the JSON body, and the timeout httpx was
told to apply. A non-2xx answer must raise, because the email job relies on the raise to have
arq retry it. The disabled client that stands in when no key is configured is asserted here too,
since it is what every development and test process actually sends through.
"""

import json

import httpx
import pytest
import structlog
from pydantic import SecretStr

RESEND_EMAILS_URL = "https://api.resend.com/emails"
SENDER = "Template <noreply@example.test>"
RECIPIENT = "reader@example.test"
SUBJECT = "Reset your password"
HTML = '<p><a href="https://app.example.test/reset-password?token=abc">Reset</a></p>'
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
API_KEY = "_".join(("re", "unit", "placeholder"))


def build_client(handler: object) -> object:
    """Return a Resend client whose HTTP calls are answered by the handler."""
    from app.clients.resend import ResendEmailClient  # noqa: PLC0415

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ResendEmailClient(SecretStr(API_KEY), SENDER, http_client)


async def test_b47_send_email_posts_the_message_to_resend_with_the_bearer_key() -> None:
    """One POST to the emails endpoint, authorized with the key and carrying the message."""
    captured_requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"id": "email-1"})

    await build_client(answer).send_email(RECIPIENT, SUBJECT, HTML)

    [request] = captured_requests
    assert request.method == "POST"
    assert str(request.url) == RESEND_EMAILS_URL
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.content) == {
        "from": SENDER,
        "to": [RECIPIENT],
        "subject": SUBJECT,
        "html": HTML,
    }


async def test_r346_send_email_sets_an_explicit_timeout_on_the_request() -> None:
    """httpx is told a finite timeout for every phase, so a hung provider cannot hang the job."""
    captured_requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"id": "email-1"})

    await build_client(answer).send_email(RECIPIENT, SUBJECT, HTML)

    timeout = captured_requests[0].extensions["timeout"]
    assert set(timeout) == {"connect", "read", "write", "pool"}
    assert all(isinstance(value, float) and value > 0 for value in timeout.values())


@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_b47_a_non_2xx_answer_raises(status_code: int) -> None:
    """A refused send raises, which is what makes arq retry the email job."""

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "refused"})

    with pytest.raises(httpx.HTTPStatusError):
        await build_client(refuse).send_email(RECIPIENT, SUBJECT, HTML)


async def test_r346_send_email_is_logged_through_the_telemetry_wrapper() -> None:
    """The send is one instrumented call naming the provider and the operation."""

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "email-1"})

    with structlog.testing.capture_logs() as captured_events:
        await build_client(answer).send_email(RECIPIENT, SUBJECT, HTML)

    telemetry_events = [event for event in captured_events if event.get("provider") == "resend"]
    assert [event["operation"] for event in telemetry_events] == ["send_email"]
    assert telemetry_events[0]["outcome"] == "success"


async def test_the_disabled_client_logs_without_the_link_or_the_token() -> None:
    """With no key configured nothing is sent, and the log line carries no secret from the body."""
    from app.clients.disabled_email import DisabledEmailClient  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        await DisabledEmailClient().send_email(RECIPIENT, SUBJECT, HTML)

    assert [event["event"] for event in captured_events] == ["password_reset_email_not_sent"]
    rendered_events = json.dumps(captured_events)
    assert "token=" not in rendered_events
    assert "reset-password" not in rendered_events
    assert RECIPIENT not in rendered_events
