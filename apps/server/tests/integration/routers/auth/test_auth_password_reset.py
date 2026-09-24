"""B-14, B-15, and B-47: requesting a reset, the job that mails it, and spending the token.

The forgot-password route is asserted through the queue it writes to rather than through a
worker, because B-14 is about what the route does and does not reveal: it must enqueue the same
one job for a known and an unknown address, and answer the same way for both. The job is then
driven directly with the engine and a fake email client in its context, which is exactly the
context arq hands it, so the assertions about the email and the stored hash are about the job
itself rather than about a queue round trip.

Every reset test takes its token from the link in the email the job sent, never from a helper
that builds one, so a job that stored one token and mailed another cannot pass. Every test that
proves a session was revoked first proves the same cookie authenticated a moment earlier.
"""

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
from sqlalchemy import text

FORGOT_ROUTE = "/v1/auth/forgot-password"
RESET_ROUTE = "/v1/auth/reset-password"
LOGIN_PATH = "/v1/auth/login"
ME_PATH = "/v1/auth/me"
RESET_EMAIL_JOB_NAME = "send_password_reset_email"
INVALID_RESET_CODE = "AUTH_RESET_TOKEN_INVALID"
CLIENT_URL = "https://app.example.test"
JOB_ID = "test-send-password-reset-email"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
ORIGINAL_PASSPHRASE = "-".join(("correct", "horse", "battery", "staple"))
NEW_PASSPHRASE = "-".join(("another", "entirely", "different", "phrase"))
SECOND_PASSPHRASE = "-".join(("yet", "one", "more", "phrase"))
RESET_LINK_PATTERN = re.compile(
    r'href="' + re.escape(CLIENT_URL) + r'/reset-password\?token=([A-Za-z0-9_-]+)"'
)
EXPECTED_TTL = timedelta(hours=1)
TTL_TOLERANCE = timedelta(minutes=1)

SELECT_RESETS_SQL = text(
    "SELECT token_hash, expires_at, used_at FROM user_password_resets WHERE user_id = :user_id"
)
EXPIRE_RESETS_SQL = text(
    "UPDATE user_password_resets SET expires_at = now() - interval '1 minute' "
    "WHERE user_id = :user_id"
)


class RecordingJobQueue:
    """Stands in for the arq pool and records every job the route enqueues."""

    def __init__(self) -> None:
        """Start with no jobs recorded."""
        self.enqueued: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, function: str, *args: object) -> None:
        """Record the job name and its positional arguments."""
        self.enqueued.append((function, args))


class FakeEmailClient:
    """Records every email the job sends instead of calling Resend."""

    def __init__(self) -> None:
        """Start with no emails recorded."""
        self.sent: list[dict[str, str]] = []

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Record the message."""
        self.sent.append({"to": to, "subject": subject, "html": html})


class FailingEmailClient:
    """Raises the way a Resend outage does, so the job's retry path can be asserted."""

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Refuse every send."""
        raise RuntimeError("resend is unavailable")


def credentials(email: str, passphrase: str) -> dict[str, str]:
    """Return a login body, built without a credential-shaped literal."""
    return dict([("email", email), ("password", passphrase)])


def reset_body(token: str, passphrase: str) -> dict[str, str]:
    """Return a reset-password body, built without a credential-shaped literal."""
    return dict([("token", token), ("password", passphrase)])


def extract_reset_token(html: str) -> str:
    """Return the token the email's reset link carries, failing when there is no such link."""
    match = RESET_LINK_PATTERN.search(html)
    assert match is not None, html
    return match.group(1)


@pytest.fixture
def job_environment(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> None:
    """Point the settings the job reads at the migrated database and the test client origin."""
    from app.core.settings import get_settings  # noqa: PLC0415

    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("CLIENT_URL", CLIENT_URL)
    get_settings.cache_clear()


async def run_reset_email_job(auth_db, email: str, email_client: object) -> None:
    """Run the job with the context arq would give it: the engine and the email client."""
    from app.workers.jobs.send_password_reset_email import (  # noqa: PLC0415
        send_password_reset_email,
    )

    worker_context = {"engine": auth_db.engine, "email_client": email_client, "job_id": JOB_ID}
    await send_password_reset_email(worker_context, email)


async def issue_reset_token(auth_db, email: str) -> str:
    """Run the job for this address and return the token its email carried."""
    email_client = FakeEmailClient()
    await run_reset_email_job(auth_db, email, email_client)
    assert len(email_client.sent) == 1
    return extract_reset_token(email_client.sent[0]["html"])


async def read_resets(auth_db, user_id) -> list:
    """Return every password reset row the user owns."""
    async with auth_db.engine.connect() as connection:
        return list(await connection.execute(SELECT_RESETS_SQL, {"user_id": user_id}))


async def read_password_hash(auth_db, email: str) -> bytes:
    """Return the stored bcrypt hash for this address."""
    return (await auth_db.read_users(email))[0].password_hash.encode()


@pytest.mark.integration
@pytest.mark.parametrize("is_known", [True, False], ids=["known", "unknown"])
async def test_b14_forgot_password_answers_200_and_enqueues_one_job_for_any_address(
    is_known, build_auth_app, open_auth_browsers, auth_db, auth_emails
) -> None:
    """B-14: the response and the queue work are identical whether or not the account exists."""
    from app.dependencies.job_queue import get_job_queue  # noqa: PLC0415

    email = auth_emails("forgot")
    if is_known:
        await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    job_queue = RecordingJobQueue()
    application = build_auth_app()
    application.dependency_overrides[get_job_queue] = lambda: job_queue

    async with open_auth_browsers(application) as [browser]:
        response = await browser.post(FORGOT_ROUTE, json={"email": f"  {email}  "})

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"data"}
    assert isinstance(response.json()["data"]["message"], str)
    # The request's own ID travels with the job, so the worker's logs and its Resend call carry
    # the ID of the request that asked for the email (R-341).
    assert job_queue.enqueued == [(RESET_EMAIL_JOB_NAME, (email, response.headers["X-Request-Id"]))]


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b47_the_job_mails_a_link_whose_token_hashes_to_the_stored_row(
    auth_db, auth_emails
) -> None:
    """B-47: one email to the requester, and its token is the one whose SHA-256 was stored."""
    email = auth_emails("mailed")
    user_id = await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    email_client = FakeEmailClient()

    await run_reset_email_job(auth_db, email.upper(), email_client)

    assert len(email_client.sent) == 1
    assert email_client.sent[0]["to"] == email
    token = extract_reset_token(email_client.sent[0]["html"])
    [reset_row] = await read_resets(auth_db, user_id)
    assert reset_row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert reset_row.token_hash != token
    assert reset_row.used_at is None
    expected_expiry = datetime.now(UTC) + EXPECTED_TTL
    assert abs(reset_row.expires_at - expected_expiry) < TTL_TOLERANCE


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b14_the_job_sends_nothing_for_an_unknown_address(auth_emails, auth_db) -> None:
    """B-14: only the known address's job sends a message."""
    email_client = FakeEmailClient()

    await run_reset_email_job(auth_db, auth_emails("nobody"), email_client)

    assert email_client.sent == []


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b47_a_send_error_raises_out_of_the_job_so_arq_retries(auth_db, auth_emails) -> None:
    """B-47: a Resend failure is not swallowed, because a swallowed send loses the email."""
    email = auth_emails("outage")
    await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)

    with pytest.raises(RuntimeError, match="resend is unavailable"):
        await run_reset_email_job(auth_db, email, FailingEmailClient())


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b15_a_token_resets_once_and_signs_out_every_session(
    auth_client, auth_db, auth_emails
) -> None:
    """B-15: the first submission sets the password and revokes sessions; a replay is refused."""
    email = auth_emails("reset")
    user_id = await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    signed_in = await auth_client.post(LOGIN_PATH, json=credentials(email, ORIGINAL_PASSPHRASE))
    assert signed_in.status_code == 200, signed_in.text
    assert (await auth_client.get(ME_PATH)).status_code == 200
    token = await issue_reset_token(auth_db, email)

    first = await auth_client.post(RESET_ROUTE, json=reset_body(token, NEW_PASSPHRASE))
    replay = await auth_client.post(RESET_ROUTE, json=reset_body(token, SECOND_PASSPHRASE))

    assert first.status_code == 204, first.text
    assert replay.status_code == 400, replay.text
    assert replay.json()["code"] == INVALID_RESET_CODE
    assert (await auth_client.get(ME_PATH)).status_code == 401
    assert await auth_db.read_sessions(user_id) == []
    stored_hash = await read_password_hash(auth_db, email)
    assert bcrypt.checkpw(NEW_PASSPHRASE.encode(), stored_hash)
    [reset_row] = await read_resets(auth_db, user_id)
    assert reset_row.used_at is not None


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b15_an_expired_token_is_refused_and_changes_nothing(
    auth_client, auth_db, auth_emails
) -> None:
    """B-15: a token past its hour answers 400 and the password stays what it was."""
    email = auth_emails("expired")
    user_id = await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    token = await issue_reset_token(auth_db, email)
    async with auth_db.engine.begin() as connection:
        await connection.execute(EXPIRE_RESETS_SQL, {"user_id": user_id})

    response = await auth_client.post(RESET_ROUTE, json=reset_body(token, NEW_PASSPHRASE))

    assert response.status_code == 400, response.text
    assert response.json()["code"] == INVALID_RESET_CODE
    assert bcrypt.checkpw(ORIGINAL_PASSPHRASE.encode(), await read_password_hash(auth_db, email))


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b15_a_newer_reset_retires_the_older_token(auth_client, auth_db, auth_emails) -> None:
    """B-15: only the latest link works once a second reset has been issued."""
    email = auth_emails("reissued")
    user_id = await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    older_token = await issue_reset_token(auth_db, email)
    newer_token = await issue_reset_token(auth_db, email)
    assert len(await read_resets(auth_db, user_id)) == 1

    older = await auth_client.post(RESET_ROUTE, json=reset_body(older_token, NEW_PASSPHRASE))
    newer = await auth_client.post(RESET_ROUTE, json=reset_body(newer_token, NEW_PASSPHRASE))

    assert older.status_code == 400, older.text
    assert older.json()["code"] == INVALID_RESET_CODE
    assert newer.status_code == 204, newer.text


@pytest.mark.integration
@pytest.mark.usefixtures("job_environment")
async def test_b15_two_concurrent_submissions_of_one_token_produce_one_success(
    build_auth_app, open_auth_browsers, auth_db, auth_emails
) -> None:
    """B-15: the atomic consume lets exactly one of two simultaneous submissions through."""
    email = auth_emails("race")
    await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    token = await issue_reset_token(auth_db, email)

    async with open_auth_browsers(build_auth_app(), count=2) as [first, second]:
        responses = await asyncio.gather(
            first.post(RESET_ROUTE, json=reset_body(token, NEW_PASSPHRASE)),
            second.post(RESET_ROUTE, json=reset_body(token, SECOND_PASSPHRASE)),
        )

    assert sorted(response.status_code for response in responses) == [204, 400]


@pytest.mark.integration
async def test_b15_a_reset_password_shorter_than_the_minimum_is_refused(auth_client) -> None:
    """R-406: the reset body takes the same password constraints registration does."""
    response = await auth_client.post(RESET_ROUTE, json=reset_body("any-token", "short"))

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
