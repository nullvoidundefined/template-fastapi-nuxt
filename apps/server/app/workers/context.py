"""The typed arq job context: what arq supplies and what the worker's startup hook adds."""

import asyncio
from typing import TypedDict

import uvicorn
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine


class WorkerContext(TypedDict, total=False):
    """The dict arq passes to lifecycle hooks and jobs, typed so mypy checks every read."""

    redis: Redis
    engine: AsyncEngine
    health_server: uvicorn.Server
    health_server_task: asyncio.Task[None]
