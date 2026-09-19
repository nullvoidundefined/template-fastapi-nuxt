"""B-3 unit tests for the worker heartbeat job in app/workers/jobs/log_worker_heartbeat.py.

The job is imported inside the test body, so a missing module fails the test rather than
collection. structlog's capture_logs() records every event the job emits; merge_contextvars runs
first in its chain, so keys the job binds into the context appear on the captured event. The job
binds arq's job_id for its own duration only (R-341), so the context holds no job_id afterwards.
"""

import importlib
from collections.abc import Iterator

import pytest
import structlog
from structlog.contextvars import clear_contextvars, get_contextvars, merge_contextvars

HEARTBEAT_JOB_MODULE = "app.workers.jobs.log_worker_heartbeat"
HEARTBEAT_EVENT_NAME = "worker_heartbeat"
HEARTBEAT_JOB_ID = "cron:log_worker_heartbeat:123"


@pytest.fixture(autouse=True)
def empty_structlog_context() -> Iterator[None]:
    """Start and end every test with an empty structlog context, so no key leaks across tests."""
    clear_contextvars()
    yield
    clear_contextvars()


async def test_b3_log_worker_heartbeat_logs_exactly_one_heartbeat_event() -> None:
    """B-3: each heartbeat run logs one worker_heartbeat event and returns None."""
    heartbeat_module = importlib.import_module(HEARTBEAT_JOB_MODULE)
    worker_context = {"job_id": HEARTBEAT_JOB_ID}

    with structlog.testing.capture_logs() as captured_events:
        heartbeat_result = await heartbeat_module.log_worker_heartbeat(worker_context)

    assert heartbeat_result is None
    assert [captured_event["event"] for captured_event in captured_events] == [HEARTBEAT_EVENT_NAME]
    assert worker_context == {"job_id": HEARTBEAT_JOB_ID}


async def test_review4_log_worker_heartbeat_binds_job_id_for_the_job_duration_only() -> None:
    """Review item 4: the heartbeat line carries arq's job_id, and the binding ends with the job."""
    heartbeat_module = importlib.import_module(HEARTBEAT_JOB_MODULE)
    worker_context = {"job_id": HEARTBEAT_JOB_ID}

    with structlog.testing.capture_logs(processors=[merge_contextvars]) as captured_events:
        await heartbeat_module.log_worker_heartbeat(worker_context)

    heartbeat_events = [
        captured_event
        for captured_event in captured_events
        if captured_event["event"] == HEARTBEAT_EVENT_NAME
    ]
    assert len(heartbeat_events) == 1
    assert heartbeat_events[0].get("job_id") == HEARTBEAT_JOB_ID
    assert "job_id" not in get_contextvars(), "job_id stays bound after the job returns"
