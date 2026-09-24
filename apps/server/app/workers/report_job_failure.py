"""Reports a job's final failure to Sentry, tagged with its arq job ID.

Every job function is decorated with `report_job_failure` where it is defined, so the function
the registry names and the function arq runs are the same object. A job that raises `Retry` is not
reported, because arq runs it again; its last try raises the underlying error, which is. The error
is logged and re-raised, so arq still records the job as failed.
"""

import functools
from collections.abc import Callable, Coroutine
from typing import Any, Concatenate

import structlog
from arq.worker import Retry

from app.clients.sentry import open_sentry_job_scope, report_sentry_exception
from app.workers.context import WorkerContext

logger = structlog.get_logger(__name__)


def report_job_failure[**P, T](
    job: Callable[Concatenate[WorkerContext, P], Coroutine[Any, Any, T]],
) -> Callable[Concatenate[WorkerContext, P], Coroutine[Any, Any, T]]:
    """Wrap a job so a failure arq will not retry is logged and reaches Sentry with the job's ID."""

    @functools.wraps(job)
    async def run_reported_job(ctx: WorkerContext, /, *args: P.args, **kwargs: P.kwargs) -> T:
        job_id = ctx.get("job_id")
        with open_sentry_job_scope(job_id):
            try:
                return await job(ctx, *args, **kwargs)
            except Retry:
                raise
            except Exception as err:
                logger.error("job_failed", job_name=job.__name__, job_id=job_id, exc_info=err)
                report_sentry_exception(err)
                raise

    return run_reported_job
