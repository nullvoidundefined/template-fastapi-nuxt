"""B-24 for account recovery: the two password-reset events, keyed by the user's ID only.

The forgot-password route never looks the address up, so it cannot name a user without leaking
whether the address has an account. The job can, so `user_password_reset_requested` is sent from
the job once a reset is issued, and never for an unknown address. `user_password_reset_completed`
is sent by the reset route, which learns the user from the token it consumed.
"""

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from tests.integration.routers.auth.test_auth_observability import RecordingPosthog
from tests.integration.routers.auth.test_auth_password_reset import (
    JOB_ID,
    ORIGINAL_PASSPHRASE,
    RESET_ROUTE,
    FakeEmailClient,
    extract_reset_token,
    job_environment,  # noqa: F401  (a fixture, used by name below)
    reset_body,
)
from tests.integration.routers.conftest import AuthAppFactory, AuthDatabase, EmailFactory

REPLACEMENT = "-".join(("recovered", "account", "test", "phrase"))


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b24_a_reset_sends_requested_then_completed_keyed_by_user_id(
    build_auth_app: AuthAppFactory,
    open_auth_browsers: Callable[..., AbstractAsyncContextManager[list[httpx.AsyncClient]]],
    auth_db: AuthDatabase,
    auth_emails: EmailFactory,
) -> None:
    """The job reports the request and the route reports the completion, with no address."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415
    from app.workers.jobs.send_password_reset_email import (  # noqa: PLC0415
        send_password_reset_email,
    )

    email = auth_emails("recovered")
    user_id = await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    recorder = RecordingPosthog()
    email_client = FakeEmailClient()
    await send_password_reset_email(
        {
            "engine": auth_db.engine,
            "email_client": email_client,
            "analytics_client": AnalyticsClient(recorder),
            "job_id": JOB_ID,
        },
        email,
    )
    token = extract_reset_token(email_client.sent[0]["html"])
    application = build_auth_app()
    application.state.analytics_client = AnalyticsClient(recorder)

    async with open_auth_browsers(application) as [browser]:
        response = await browser.post(RESET_ROUTE, json=reset_body(token, REPLACEMENT))

    assert response.status_code == 204, response.text
    assert [capture["event"] for capture in recorder.captures] == [
        "user_password_reset_requested",
        "user_password_reset_completed",
    ]
    assert {capture["distinct_id"] for capture in recorder.captures} == {str(user_id)}
    assert "@" not in json.dumps(recorder.captures)


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b24_an_unknown_address_sends_no_reset_event(
    auth_db: AuthDatabase, auth_emails: EmailFactory
) -> None:
    """Nothing is reported for an address with no account, so analytics cannot enumerate them."""
    from app.clients.analytics import AnalyticsClient  # noqa: PLC0415
    from app.workers.jobs.send_password_reset_email import (  # noqa: PLC0415
        send_password_reset_email,
    )

    recorder = RecordingPosthog()
    await send_password_reset_email(
        {
            "engine": auth_db.engine,
            "email_client": FakeEmailClient(),
            "analytics_client": AnalyticsClient(recorder),
            "job_id": JOB_ID,
        },
        auth_emails("nobody"),
    )

    assert recorder.captures == []
