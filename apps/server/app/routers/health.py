"""Liveness and readiness probes, registered before every application router (R-345)."""

import asyncio

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

READINESS_TIMEOUT_SECONDS = 2

router = APIRouter(tags=["health"])
logger = structlog.get_logger()


@router.get("/health")
async def read_liveness() -> dict[str, str]:
    """Answer 200 without touching any dependency."""
    return {"status": "ok"}


@router.get("/health/ready")
async def read_readiness(request: Request, response: Response) -> dict[str, str]:
    """Answer 200 when Postgres answers within the deadline, and 503 otherwise."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as err:
        logger.warning("readiness_db_failed", exc_info=err)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "db": "disconnected"}
    return {"status": "ok", "db": "connected"}
