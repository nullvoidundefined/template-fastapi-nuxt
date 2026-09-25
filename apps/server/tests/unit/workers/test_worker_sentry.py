"""IAN-344 unit tests: the arq worker reports a job's final failure to Sentry, tagged with job_id.

Three properties are pinned. Worker startup initializes Sentry when SENTRY_DSN is set, as the API
does. A registered job that fails for good reaches Sentry with the arq job ID as a tag. And a job
that raises `Retry` is not reported, because arq runs it again and only the last failure matters.

Jobs are taken from the `WorkerSettings` arq reads, so what runs is what arq would run, and the
engine points at a closed local port so the job's real database call fails. Events are captured
at the SDK's transport, the last point before the network.
"""

from collections.abc import Iterator
from typing import Any, cast

import pytest
import sentry_sdk
from arq.typing import WorkerCoroutine
from arq.worker import Retry
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.unit.clients.test_sentry import TEST_DSN, RecordingTransport
from tests.unit.workers.test_worker_settings import (
    FakeRedis,
    find_free_port,
    import_worker_settings_module,
    worker_environment,  # noqa: F401 (a fixture, used by name)
)

JOB_ID = "job-ian344-1"
CLEANUP_JOB_NAME = "delete_expired_rows"
RESET_EMAIL_JOB_NAME = "send_password_reset_email"
RESET_EMAIL_MAX_TRIES = 3


@pytest.fixture(autouse=True)
def inert_sentry() -> Iterator[None]:
    """Leave the process with no Sentry client at all, whatever the test initialized.

    `sentry_sdk.init()` without a DSN still builds a client with the default integrations, so the
    client is removed outright instead, as `initialize_sentry` does without a DSN.
    """
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


@pytest.fixture
def recording_transport() -> RecordingTransport:
    """Initialize Sentry through the app's own initializer and record what it would send."""
    from app.clients.sentry import initialize_sentry  # noqa: PLC0415
    from app.core.settings import Settings  # noqa: PLC0415

    initialize_sentry(
        Settings(database_url=UNREACHABLE_DATABASE_URL, sentry_dsn=TEST_DSN, environment="test")
    )
    transport = RecordingTransport()
    sentry_sdk.get_client().transport = transport
    return transport


def find_registered_job(job_name: str) -> WorkerCoroutine:
    """Return the coroutine WorkerSettings registers under the name, as a job or a cron job."""
    worker_settings = import_worker_settings_module().WorkerSettings
    for registered_job in [*worker_settings.functions, *worker_settings.cron_jobs]:
        if registered_job.name == job_name:
            # WorkerSettings comes through import_module, so mypy sees it as Any; arq types every
            # registered coroutine as a WorkerCoroutine.
            return cast("WorkerCoroutine", registered_job.coroutine)
    raise AssertionError(f"{job_name} is not registered")


def build_job_context(job_try: int) -> dict[str, Any]:
    """Return the context arq passes a job, with an engine whose connect is refused."""
    return {
        "job_id": JOB_ID,
        "job_try": job_try,
        "engine": create_async_engine(UNREACHABLE_DATABASE_URL),
    }


@pytest.mark.usefixtures("worker_environment")
async def test_ian344_worker_startup_initializes_sentry_when_a_dsn_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SENTRY_DSN set, the worker process reports errors just as the API does."""
    from tests.conftest import clear_settings_cache  # noqa: PLC0415

    monkeypatch.setenv("SENTRY_DSN", TEST_DSN)
    monkeypatch.setenv("WORKER_PORT", str(find_free_port()))
    clear_settings_cache()
    worker_settings_module = import_worker_settings_module()
    worker_context: dict[str, Any] = {"redis": FakeRedis()}

    await worker_settings_module.start_worker_resources(worker_context)
    try:
        is_sentry_active = sentry_sdk.get_client().is_active()
    finally:
        await worker_settings_module.stop_worker_resources(worker_context)

    assert is_sentry_active is True


@pytest.mark.usefixtures("worker_environment")
async def test_ian344_a_failed_cron_job_reaches_sentry_tagged_with_its_job_id(
    recording_transport: RecordingTransport,
) -> None:
    """The cleanup job's failure is reported once, carrying the arq job ID, and still raised."""
    delete_expired_rows = find_registered_job(CLEANUP_JOB_NAME)
    job_context = build_job_context(job_try=1)

    try:
        with pytest.raises(OSError):
            await delete_expired_rows(job_context)
    finally:
        await job_context["engine"].dispose()

    assert len(recording_transport.events) == 1, recording_transport.events
    [event] = recording_transport.events
    assert event.get("tags", {}).get("job_id") == JOB_ID


@pytest.mark.usefixtures("worker_environment")
async def test_ian344_the_reset_email_job_reports_only_its_last_try(
    recording_transport: RecordingTransport,
) -> None:
    """A try arq will run again raises Retry unreported; the last try's failure is reported."""
    send_password_reset_email = find_registered_job(RESET_EMAIL_JOB_NAME)
    early_context = build_job_context(job_try=1)
    last_context = build_job_context(job_try=RESET_EMAIL_MAX_TRIES)

    try:
        with pytest.raises(Retry):
            await send_password_reset_email(early_context, "person@example.test")
        events_after_retry = list(recording_transport.events)
        with pytest.raises(OSError):
            await send_password_reset_email(last_context, "person@example.test")
    finally:
        await early_context["engine"].dispose()
        await last_context["engine"].dispose()

    assert events_after_retry == []
    assert len(recording_transport.events) == 1, recording_transport.events
    [event] = recording_transport.events
    assert event.get("tags", {}).get("job_id") == JOB_ID
    assert "person@example.test" not in repr(event)
