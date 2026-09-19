"""Liveness and readiness probes, registered before every application router (R-345)."""

import asyncio

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.health import HealthLiveness, HealthReadiness

READINESS_TIMEOUT_SECONDS = 2

router = APIRouter(tags=["health"])
logger = structlog.get_logger()


@router.get("/health", response_model=HealthLiveness)
async def read_liveness() -> HealthLiveness:
    """Answer 200 without touching any dependency."""
    return HealthLiveness(status="ok")


@router.get("/health/ready", response_model=HealthReadiness)
async def read_readiness(request: Request, response: Response) -> HealthReadiness:
    """Answer 200 when Postgres answers within the deadline, and 503 otherwise."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as err:
        logger.warning("readiness_db_failed", exc_info=err)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthReadiness(status="degraded", db="disconnected")
    return HealthReadiness(status="ok", db="connected")
