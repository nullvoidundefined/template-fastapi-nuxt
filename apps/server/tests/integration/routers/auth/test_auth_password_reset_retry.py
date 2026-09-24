"""B-47 through a real arq worker: a failed send is retried, and the job carries the request ID.

The earlier tests asserted that the job raises and that `max_tries` is 3, which both hold while
arq retries nothing: arq only retries a job that raises `arq.worker.Retry`, and marks any other
exception failed on its first try. So this drives the registered job through `arq.worker.Worker`
against a real Redis and counts the sends, which is the only assertion that fails when the retry
does not happen.
"""

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
import structlog
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker
from redis.exceptions import RedisError

ORIGINAL_PASSPHRASE = "-".join(("retry", "reset", "test", "phrase"))
CLIENT_URL = "https://app.example.test"
# Its own Redis database, so flushing it cannot empty the counters another suite relies on.
RETRY_REDIS_DATABASE = 12
REQUEST_ID = "req-reset-retry-0001"


class FlakyEmailClient:
    """Fails the first send the way a Resend 503 does, then succeeds, recording what it saw."""

    def __init__(self) -> None:
        """Start with no attempts."""
        self.attempts = 0
        self.delivered: list[str] = []
        self.request_ids: list[Any] = []

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Raise on the first attempt; record the recipient and the bound request ID on each."""
        self.attempts += 1
        self.request_ids.append(structlog.contextvars.get_contextvars().get("request_id"))
        if self.attempts == 1:
            raise RuntimeError("resend answered 503")
        self.delivered.append(to)


def build_retry_redis_url() -> str:
    """Return the retry test's Redis database URL, or skip when TEST_REDIS_URL is unset."""
    test_redis_url = os.environ.get("TEST_REDIS_URL")
    if not test_redis_url:
        pytest.skip("IAN-312: TEST_REDIS_URL is unset; the arq retry test needs a real Redis")
    parts = urlsplit(test_redis_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{RETRY_REDIS_DATABASE}", parts.query, parts.fragment)
    )


async def open_flushed_pool(redis_url: str) -> ArqRedis:
    """Open an arq pool on the retry database and empty it, skipping when Redis is down."""
    try:
        pool = await create_pool(RedisSettings.from_dsn(redis_url))
        await pool.flushdb()
    except (OSError, RedisError):
        pytest.skip("IAN-312: the Redis at TEST_REDIS_URL did not answer; the retry test needs it")
    return pool


@pytest.fixture
def worker_environment(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> str:
    """Point the settings the worker module reads at test services, and shorten the retry delay."""
    from app.core.settings import get_settings  # noqa: PLC0415

    redis_url = build_retry_redis_url()
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("CLIENT_URL", CLIENT_URL)
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.workers.jobs.send_password_reset_email.RESET_EMAIL_RETRY_DELAY_SECONDS",
        0.1,
        raising=False,
    )
    return redis_url


@pytest.mark.integration
async def test_b47_arq_retries_a_failed_send_and_the_second_try_delivers(
    worker_environment, auth_db, auth_emails
) -> None:
    """B-47: a send that fails once is retried by arq, and the retry delivers the email."""
    from app.constants.job_names import RESET_EMAIL_JOB_NAME  # noqa: PLC0415
    from app.workers.settings import WorkerSettings  # noqa: PLC0415

    email = auth_emails("retried")
    await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    pool = await open_flushed_pool(worker_environment)
    email_client = FlakyEmailClient()
    try:
        await pool.enqueue_job(RESET_EMAIL_JOB_NAME, email, REQUEST_ID)
        worker = Worker(
            functions=WorkerSettings.functions,
            redis_pool=pool,
            burst=True,
            poll_delay=0.05,
            ctx={"engine": auth_db.engine, "email_client": email_client},
            handle_signals=False,
        )
        await worker.main()
    finally:
        await pool.aclose()

    assert email_client.attempts == 2
    assert email_client.delivered == [email]
    assert worker.jobs_retried == 1
    assert worker.jobs_failed == 0


@pytest.mark.integration
async def test_b47_the_last_try_fails_with_the_real_error_instead_of_asking_again(
    worker_environment, auth_db, auth_emails
) -> None:
    """R-344: on its final try the job raises the provider's error, so the failure is logged."""
    from arq.worker import Retry  # noqa: PLC0415

    from app.workers.jobs.send_password_reset_email import (  # noqa: PLC0415
        send_password_reset_email,
    )

    email = auth_emails("exhausted")
    await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    email_client = FlakyEmailClient()
    final_try = 3

    try:
        await send_password_reset_email(
            {"engine": auth_db.engine, "email_client": email_client, "job_try": final_try},
            email,
            REQUEST_ID,
        )
    except Retry as retry:
        raise AssertionError("the final try asked arq for a fourth one") from retry
    except RuntimeError as err:
        assert "503" in str(err)
    else:
        raise AssertionError("the final try swallowed the provider error")


@pytest.mark.integration
async def test_r341_the_job_binds_the_request_id_of_the_request_that_enqueued_it(
    worker_environment, auth_db, auth_emails
) -> None:
    """R-341: the send runs with the forgot-password request's ID bound, so it is forwarded."""
    from app.workers.jobs.send_password_reset_email import (  # noqa: PLC0415
        send_password_reset_email,
    )

    email = auth_emails("correlated")
    await auth_db.seed_user(email, ORIGINAL_PASSPHRASE)
    email_client = FlakyEmailClient()
    email_client.attempts = 1  # past the scripted failure, so this single call delivers

    try:
        await send_password_reset_email(
            {"engine": auth_db.engine, "email_client": email_client, "job_id": "j", "job_try": 1},
            email,
            REQUEST_ID,
        )
    except TypeError as err:
        raise AssertionError(f"the job does not accept the request ID: {err}") from err

    assert email_client.delivered == [email]
    assert email_client.request_ids == [REQUEST_ID]
