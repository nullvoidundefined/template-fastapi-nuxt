"""The worker's heartbeat: one log line every five minutes, its only job until slice 04.

arq refuses to start a worker with no function or cron job registered, and the heartbeat also
lets the logs show a worker that is alive but idle. Like every job, it binds its arq job ID into
the log context for the length of the run (R-341).
"""

import structlog

from app.workers.context import WorkerContext

logger = structlog.get_logger()


async def log_worker_heartbeat(ctx: WorkerContext) -> None:
    """Log one `worker_heartbeat` event carrying the job ID."""
    with structlog.contextvars.bound_contextvars(job_id=ctx["job_id"]):
        logger.info("worker_heartbeat")
