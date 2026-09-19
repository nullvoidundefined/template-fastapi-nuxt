"""B-3 unit tests for the worker heartbeat job in app/workers/jobs/log_worker_heartbeat.py.

The job is imported inside the test body, so a missing module fails the test rather than
collection. structlog's capture_logs() records every event the job emits, so the test checks
that one call produces exactly one `worker_heartbeat` event and nothing else.
"""

import importlib
from typing import Any

import structlog

HEARTBEAT_JOB_MODULE = "app.workers.jobs.log_worker_heartbeat"
HEARTBEAT_EVENT_NAME = "worker_heartbeat"


async def test_b3_log_worker_heartbeat_logs_exactly_one_heartbeat_event() -> None:
    """B-3: each heartbeat run logs one worker_heartbeat event and returns None."""
    heartbeat_module = importlib.import_module(HEARTBEAT_JOB_MODULE)
    worker_context: dict[str, Any] = {}

    with structlog.testing.capture_logs() as captured_events:
        heartbeat_result = await heartbeat_module.log_worker_heartbeat(worker_context)

    assert heartbeat_result is None
    assert [captured_event["event"] for captured_event in captured_events] == [HEARTBEAT_EVENT_NAME]
    assert worker_context == {}
