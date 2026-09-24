"""The API's handle on the arq queue, built once in the lifespan and closed with it.

The pool is arq's own Redis client built from REDIS_URL without connecting. `arq.create_pool`
pings Redis at startup and retries before raising, which would make the API refuse to start
during a Redis outage; the rate limiter already treats that outage as something the API survives,
costing only the four auth paths, and a queue that took the whole process down with it would
undo that. The connection is made on the first enqueue instead, bounded by the same socket
timeouts the rate limiter uses.

With REDIS_URL unset there is no queue to write to, which is only legitimate outside a deployed
environment. The stand-in then raises on enqueue with a message naming the variable, so the
first forgot-password request says exactly what is missing rather than failing somewhere in arq.
"""

from typing import Protocol

from arq.connections import ArqRedis

from app.core.settings import Settings

QUEUE_REDIS_TIMEOUT_SECONDS = 2
JOB_QUEUE_UNCONFIGURED_MESSAGE = "REDIS_URL is not set, so no job can be enqueued"


class JobQueue(Protocol):
    """The one call a route makes on the queue: enqueue a job by name with its arguments."""

    async def enqueue_job(self, function: str, *args: object) -> object:
        """Put one job on the queue for the worker to run."""
        ...


class JobQueueUnconfiguredError(RuntimeError):
    """A job was enqueued in a process started without REDIS_URL."""


class UnconfiguredJobQueue:
    """Stands in for the arq pool when REDIS_URL is unset, refusing every enqueue by name."""

    async def enqueue_job(self, function: str, *args: object) -> object:
        """Raise, naming the variable that would have made a queue available."""
        raise JobQueueUnconfiguredError(JOB_QUEUE_UNCONFIGURED_MESSAGE)

    async def aclose(self) -> None:
        """Release nothing, so the lifespan can close either queue the same way."""


def create_job_queue(settings: Settings) -> ArqRedis | UnconfiguredJobQueue:
    """Return arq's client for REDIS_URL without connecting, or the stand-in when it is unset."""
    if settings.redis_url is None:
        return UnconfiguredJobQueue()
    job_queue: ArqRedis = ArqRedis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=QUEUE_REDIS_TIMEOUT_SECONDS,
        socket_timeout=QUEUE_REDIS_TIMEOUT_SECONDS,
    )
    return job_queue
