"""The typed arq job context: what arq supplies and what the worker's startup hook adds."""

import asyncio
from typing import Protocol, TypedDict

import uvicorn
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clients.email_sender import EmailSender


class WorkerEmailClient(EmailSender, Protocol):
    """The email client the worker holds: it sends, and it is closed when the worker stops."""

    async def close(self) -> None:
        """Release whatever the client holds open."""
        ...


class WorkerContext(TypedDict, total=False):
    """The dict arq passes to lifecycle hooks and jobs, typed so mypy checks every read."""

    redis: Redis
    job_id: str
    job_try: int
    engine: AsyncEngine
    email_client: WorkerEmailClient
    health_server: uvicorn.Server
    health_server_task: asyncio.Task[None]
