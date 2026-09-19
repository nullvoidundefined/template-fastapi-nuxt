"""arq worker configuration: the queue connection, the job registry, and lifecycle hooks.

arq imports `WorkerSettings` to start the process (`arq app.workers.settings.WorkerSettings`), so
this is the one module allowed to read settings at import time; nothing else imports it. The only
job until slice 04 is a five-minute heartbeat cron job, because arq refuses to start without one.
Startup opens the engine and serves the health probes on WORKER_PORT as a background uvicorn
server, which the container's HEALTHCHECK calls; shutdown stops both.
"""

import asyncio

import structlog
import uvicorn
from arq.connections import RedisSettings
from arq.cron import cron

from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.engine import create_database_engine
from app.workers.context import WorkerContext
from app.workers.health import create_worker_health_app
from app.workers.jobs.log_worker_heartbeat import log_worker_heartbeat

HEALTH_SERVER_HOST = "0.0.0.0"  # noqa: S104 (the container's HEALTHCHECK and the platform probe it)
HEALTH_SERVER_START_TIMEOUT_SECONDS = 5
HEARTBEAT_MINUTES = set(range(0, 60, 5))


async def start_worker_resources(ctx: WorkerContext) -> None:
    """Open the engine and start the probe server once per worker process."""
    settings = get_settings()
    configure_logging(settings)
    ctx["engine"] = create_database_engine(settings)
    health_app = create_worker_health_app(ctx["engine"], ctx["redis"])
    server = uvicorn.Server(
        uvicorn.Config(
            health_app,
            host=HEALTH_SERVER_HOST,
            port=settings.worker_port,
            log_config=None,
            access_log=False,  # the HEALTHCHECK calls it every 10 seconds
        )
    )
    ctx["health_server"] = server
    ctx["health_server_task"] = asyncio.create_task(server.serve())
    await wait_for_server_start(server)
    structlog.get_logger().info("worker_started", worker_port=settings.worker_port)


async def wait_for_server_start(server: uvicorn.Server) -> None:
    """Return once the probe server is listening, so the port is bound before jobs start."""
    async with asyncio.timeout(HEALTH_SERVER_START_TIMEOUT_SECONDS):
        while not server.started:
            await asyncio.sleep(0.01)


async def stop_worker_resources(ctx: WorkerContext) -> None:
    """Stop the probe server, wait until its port is released, and dispose the engine."""
    ctx["health_server"].should_exit = True
    await ctx["health_server_task"]
    await ctx["engine"].dispose()
    structlog.get_logger().info("worker_stopped")


def build_redis_settings(settings: Settings) -> RedisSettings:
    """Return arq's connection settings from REDIS_URL, which the worker cannot run without."""
    if settings.redis_url is None:
        raise RuntimeError("REDIS_URL is required to run the worker")
    return RedisSettings.from_dsn(settings.redis_url.get_secret_value())


class WorkerSettings:
    """The class arq reads: the heartbeat cron job, the Redis connection, and the hooks."""

    functions: list[object] = []
    cron_jobs = [
        cron(
            log_worker_heartbeat,  # type: ignore[arg-type]  # arq's protocol wants *args jobs never take
            name="log_worker_heartbeat",
            minute=HEARTBEAT_MINUTES,
            run_at_startup=False,
        )
    ]
    redis_settings = build_redis_settings(get_settings())
    on_startup = start_worker_resources
    on_shutdown = stop_worker_resources
    max_jobs = 10
    job_timeout = 300
    max_tries = 3
    health_check_interval = 30
