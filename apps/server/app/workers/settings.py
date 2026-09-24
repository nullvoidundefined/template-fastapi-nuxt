"""arq worker configuration: the queue connection, the job registry, and lifecycle hooks.

arq imports `WorkerSettings` to start the process (`arq app.workers.settings.WorkerSettings`), so
this is the one module allowed to read settings at import time; nothing else imports it. The jobs
are the password-reset email, retried up to three tries, and a five-minute heartbeat cron job.
Startup opens the engine, builds the email client (Resend, or a logging stand-in without a key),
and serves the health probes on WORKER_PORT as a background uvicorn server, which the container's
HEALTHCHECK calls; shutdown stops the server and closes the rest.
"""

import asyncio

import structlog
import uvicorn
from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from app.clients.disabled_email import DisabledEmailClient
from app.clients.resend import ResendEmailClient
from app.constants.job_names import RESET_EMAIL_JOB_NAME
from app.constants.password_reset import RESET_EMAIL_MAX_TRIES
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.engine import create_database_engine
from app.workers.context import WorkerContext, WorkerEmailClient
from app.workers.health import create_worker_health_app
from app.workers.jobs.log_worker_heartbeat import log_worker_heartbeat
from app.workers.jobs.send_password_reset_email import send_password_reset_email

HEALTH_SERVER_HOST = "0.0.0.0"  # noqa: S104 (the container's HEALTHCHECK and the platform probe it)
HEALTH_SERVER_START_TIMEOUT_SECONDS = 5
HEARTBEAT_MINUTES = set(range(0, 60, 5))
# Three tries in total: a Resend outage long enough to outlast them is one an operator should see
# in the failed-job log rather than one the queue keeps absorbing.


async def start_worker_resources(ctx: WorkerContext) -> None:
    """Open the engine, build the email client, and start the probe server once per process."""
    settings = get_settings()
    configure_logging(settings)
    ctx["engine"] = create_database_engine(settings)
    ctx["email_client"] = create_email_client(settings)
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


def create_email_client(settings: Settings) -> WorkerEmailClient:
    """Return Resend when a key is configured, and the logging stand-in with a warning when not."""
    if settings.resend_api_key is None:
        structlog.get_logger().warning("email_disabled", reason="resend_api_key_unset")
        return DisabledEmailClient()
    return ResendEmailClient(settings.resend_api_key, settings.email_from)


async def wait_for_server_start(server: uvicorn.Server) -> None:
    """Return once the probe server is listening, so the port is bound before jobs start."""
    async with asyncio.timeout(HEALTH_SERVER_START_TIMEOUT_SECONDS):
        while not server.started:
            await asyncio.sleep(0.01)


async def stop_worker_resources(ctx: WorkerContext) -> None:
    """Stop the probe server, wait until its port is released, and close the clients."""
    ctx["health_server"].should_exit = True
    await ctx["health_server_task"]
    await ctx["email_client"].close()
    await ctx["engine"].dispose()
    structlog.get_logger().info("worker_stopped")


def build_redis_settings(settings: Settings) -> RedisSettings:
    """Return arq's connection settings from REDIS_URL, which the worker cannot run without."""
    if settings.redis_url is None:
        raise RuntimeError("REDIS_URL is required to run the worker")
    return RedisSettings.from_dsn(settings.redis_url.get_secret_value())


class WorkerSettings:
    """The class arq reads: the jobs, the heartbeat cron job, the Redis connection, the hooks."""

    functions = [
        func(
            send_password_reset_email,  # type: ignore[arg-type]  # arq's protocol wants *args
            name=RESET_EMAIL_JOB_NAME,
            max_tries=RESET_EMAIL_MAX_TRIES,
        )
    ]
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
