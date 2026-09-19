"""B-3 unit tests for the arq worker configuration in app/workers/settings.py.

`WorkerSettings` is read by arq at import time, so each test sets REDIS_URL and DATABASE_URL,
clears the settings cache, drops any earlier import of the module, and imports it fresh inside
the test body; a missing module therefore fails each test rather than collection. The lifecycle
test drives `start_worker_resources` with a context holding a fake Redis, as arq would supply
the real one, and checks over a real socket that the probe server answers on WORKER_PORT and
that `stop_worker_resources` releases the port.
"""

import asyncio
import importlib
import socket
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import httpx
import pytest
import structlog

from tests.conftest import UNREACHABLE_DATABASE_URL, clear_settings_cache

WORKER_SETTINGS_MODULE = "app.workers.settings"
WORKER_REDIS_HOST = "127.0.0.1"
WORKER_REDIS_PORT = 6390
WORKER_REDIS_DATABASE = 2
PROBE_HOST = "127.0.0.1"
SERVER_START_DEADLINE_SECONDS = 5
SERVER_POLL_INTERVAL_SECONDS = 0.05


class FakeRedis:
    """Redis client stand-in that arq would otherwise place in ctx["redis"]."""

    async def ping(self) -> bool:
        return True


def find_free_port() -> int:
    """Return a local TCP port that nothing is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind((PROBE_HOST, 0))
        return int(probe_socket.getsockname()[1])


def build_worker_redis_url() -> str:
    """Return the Redis URL the worker settings must parse into host, port, and database."""
    return f"redis://{WORKER_REDIS_HOST}:{WORKER_REDIS_PORT}/{WORKER_REDIS_DATABASE}"


@pytest.fixture
def worker_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set the worker's environment, clear cached settings, and restore logging afterwards."""
    monkeypatch.setenv("REDIS_URL", build_worker_redis_url())
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delitem(sys.modules, WORKER_SETTINGS_MODULE, raising=False)
    original_structlog_config = structlog.get_config()
    clear_settings_cache()
    yield
    structlog.configure(**original_structlog_config)
    clear_settings_cache()
    sys.modules.pop(WORKER_SETTINGS_MODULE, None)


def import_worker_settings_module() -> ModuleType:
    """Import app.workers.settings fresh, so WorkerSettings reads the patched environment."""
    return importlib.import_module(WORKER_SETTINGS_MODULE)


async def get_probe_liveness(port: int) -> httpx.Response:
    """GET /health on the probe port, retrying until the background server has bound it."""
    probe_url = f"http://{PROBE_HOST}:{port}/health"
    async with httpx.AsyncClient() as client, asyncio.timeout(SERVER_START_DEADLINE_SECONDS):
        while True:
            try:
                return await client.get(probe_url)
            except httpx.ConnectError:
                await asyncio.sleep(SERVER_POLL_INTERVAL_SECONDS)


async def is_port_accepting_connections(port: int) -> bool:
    """Return whether a new TCP connection to the probe port succeeds."""
    try:
        _reader, writer = await asyncio.open_connection(PROBE_HOST, port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


@pytest.mark.usefixtures("worker_environment")
def test_b3_worker_settings_register_no_jobs() -> None:
    """B-3: the worker starts with an empty job registry until slice 04 adds the first job."""
    worker_settings_module = import_worker_settings_module()

    assert worker_settings_module.WorkerSettings.functions == []


@pytest.mark.usefixtures("worker_environment")
def test_b3_worker_settings_read_redis_host_port_and_database_from_redis_url() -> None:
    """B-3: redis_settings is parsed from REDIS_URL, so the worker connects where it says."""
    worker_settings_module = import_worker_settings_module()

    redis_settings = worker_settings_module.WorkerSettings.redis_settings

    assert redis_settings.host == WORKER_REDIS_HOST
    assert redis_settings.port == WORKER_REDIS_PORT
    assert redis_settings.database == WORKER_REDIS_DATABASE


@pytest.mark.usefixtures("worker_environment")
def test_b3_worker_settings_wire_the_lifecycle_hooks() -> None:
    """B-3: arq runs start_worker_resources on startup and stop_worker_resources on shutdown."""
    worker_settings_module = import_worker_settings_module()
    worker_settings = worker_settings_module.WorkerSettings

    assert worker_settings.on_startup is worker_settings_module.start_worker_resources
    assert worker_settings.on_shutdown is worker_settings_module.stop_worker_resources


@pytest.mark.usefixtures("worker_environment")
async def test_b3_worker_lifecycle_serves_the_probe_on_worker_port_and_releases_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-3: startup serves GET /health on WORKER_PORT; shutdown stops the server and the port."""
    probe_port = find_free_port()
    monkeypatch.setenv("WORKER_PORT", str(probe_port))
    clear_settings_cache()
    worker_settings_module = import_worker_settings_module()
    worker_context: dict[str, Any] = {"redis": FakeRedis()}

    await worker_settings_module.start_worker_resources(worker_context)
    try:
        liveness_response = await get_probe_liveness(probe_port)
    finally:
        await worker_settings_module.stop_worker_resources(worker_context)

    assert liveness_response.status_code == 200
    assert liveness_response.json() == {"status": "ok"}
    assert "engine" in worker_context
    assert not await is_port_accepting_connections(probe_port)


HEARTBEAT_JOB_NAME = "log_worker_heartbeat"
HEARTBEAT_JOB_MODULE = "app.workers.jobs.log_worker_heartbeat"
HEARTBEAT_MINUTES = set(range(0, 60, 5))


@pytest.mark.usefixtures("worker_environment")
async def test_b3_worker_settings_construct_an_arq_worker_without_raising() -> None:
    """B-3: arq accepts WorkerSettings, so the worker container does not crash at startup.

    Worker construction registers jobs and binds the event loop but opens no Redis connection
    (the pool is created later in Worker.main), so this runs arq's own registration check, which
    raises "at least one function or cron_job must be registered" on an empty registry. The test
    is async so arq binds the running loop, and signal handling is off so the test loop keeps its
    own SIGINT and SIGTERM handlers.
    """
    from arq.worker import create_worker  # noqa: PLC0415 (the test owns the import timing)

    worker_settings_module = import_worker_settings_module()

    worker = create_worker(worker_settings_module.WorkerSettings, handle_signals=False)

    assert HEARTBEAT_JOB_NAME in worker.functions


@pytest.mark.usefixtures("worker_environment")
def test_b3_worker_settings_schedule_the_heartbeat_every_five_minutes() -> None:
    """B-3: one cron job runs log_worker_heartbeat on minutes 0, 5, ..., 55, not at startup."""
    from arq.cron import CronJob  # noqa: PLC0415 (the test owns the import timing)

    worker_settings_module = import_worker_settings_module()
    heartbeat_module = importlib.import_module(HEARTBEAT_JOB_MODULE)
    worker_settings = worker_settings_module.WorkerSettings

    cron_jobs = list(worker_settings.cron_jobs)

    assert len(cron_jobs) == 1
    [heartbeat_cron_job] = cron_jobs
    assert isinstance(heartbeat_cron_job, CronJob)
    assert heartbeat_cron_job.coroutine is heartbeat_module.log_worker_heartbeat
    assert set(heartbeat_cron_job.minute) == HEARTBEAT_MINUTES
    assert heartbeat_cron_job.run_at_startup is False
    assert worker_settings.functions == []
