"""The worker's liveness and readiness probes (R-345), served on WORKER_PORT beside arq.

`/health` answers without touching any dependency, so the container is restarted only when the
process itself is stuck. `/health/ready` checks Postgres (`SELECT 1`) and Redis (`PING`)
concurrently, each within READINESS_TIMEOUT_SECONDS, and answers 503 naming each failed
dependency, so the container's HEALTHCHECK reports unhealthy while either is unreachable.
"""

import asyncio

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

READINESS_TIMEOUT_SECONDS = 2
PROBE_ERRORS = (OSError, SQLAlchemyError, RedisError)

logger = structlog.get_logger()


def create_worker_health_app(engine: AsyncEngine, redis: Redis) -> Starlette:
    """Build the probe app over the worker's own engine and Redis connection."""

    async def read_liveness(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def read_readiness(_request: Request) -> JSONResponse:
        is_database_up, is_redis_up = await asyncio.gather(
            check_database(engine), check_redis(redis)
        )
        return build_readiness_response(is_database_up, is_redis_up)

    return Starlette(
        routes=[
            Route("/health", read_liveness, methods=["GET"]),
            Route("/health/ready", read_readiness, methods=["GET"]),
        ]
    )


async def check_database(engine: AsyncEngine) -> bool:
    """Return True when Postgres answers `SELECT 1` within the deadline."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except PROBE_ERRORS as err:
        logger.warning("worker_readiness_db_failed", exc_info=err)
        return False
    return True


async def check_redis(redis: Redis) -> bool:
    """Return True when Redis answers `PING` within the deadline."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await redis.ping()
    except PROBE_ERRORS as err:
        logger.warning("worker_readiness_redis_failed", exc_info=err)
        return False
    return True


def build_readiness_response(is_database_up: bool, is_redis_up: bool) -> JSONResponse:
    """Answer 200 when both dependencies are up, else 503 naming each one's state."""
    is_ready = is_database_up and is_redis_up
    body = {
        "status": "ok" if is_ready else "degraded",
        "db": "connected" if is_database_up else "disconnected",
        "redis": "connected" if is_redis_up else "disconnected",
    }
    return JSONResponse(body, status_code=200 if is_ready else 503)
