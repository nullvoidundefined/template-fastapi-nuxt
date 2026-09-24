"""Provides the application's job queue to a route through the dependency chain.

The queue is built once in the lifespan and kept on the application's state, so every request
shares one Redis connection pool. Routes declare `RequestJobQueue` rather than reading the state
themselves, which is what lets a test swap in a recording queue with `dependency_overrides`.
"""

from typing import Annotated, cast

from fastapi import Depends
from starlette.requests import Request

from app.clients.job_queue import JobQueue


def get_job_queue(request: Request) -> JobQueue:
    """Return the queue the lifespan stored on the application."""
    return cast("JobQueue", request.app.state.job_queue)


RequestJobQueue = Annotated[JobQueue, Depends(get_job_queue)]
