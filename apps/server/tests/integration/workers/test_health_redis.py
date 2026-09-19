"""B-3 integration tests: the worker's readiness probe against a real redis-py client.

The first test points a real `redis.asyncio.Redis` at a closed local port, so the probe must
translate a genuine connection failure into 503 with redis disconnected. The second runs only
when TEST_REDIS_URL names a real Redis, and is skipped with a reason naming the variable
otherwise, the same way the Postgres integration test skips without TEST_DATABASE_URL. The
database side uses a healthy fake engine so these tests isolate the Redis half of the probe.
"""

import importlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

WORKER_HEALTH_MODULE = "app.workers.health"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
TEST_BASE_URL = "http://worker-health"


class HealthyConnection:
    """Connection stand-in whose execute() always succeeds."""

    async def execute(self, _statement: Any) -> None:
        return None


class HealthyEngine:
    """Engine stand-in whose connect() always yields a working connection."""

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[HealthyConnection]:
        yield HealthyConnection()

    async def dispose(self) -> None:
        return None


async def request_worker_readiness(redis_url: str) -> httpx.Response:
    """Build the worker probe app around a real Redis client and GET /health/ready once."""
    health_module = importlib.import_module(WORKER_HEALTH_MODULE)
    redis_asyncio = importlib.import_module("redis.asyncio")
    redis_client = redis_asyncio.Redis.from_url(redis_url)
    try:
        probe_app = health_module.create_worker_health_app(HealthyEngine(), redis_client)
        transport = httpx.ASGITransport(app=probe_app)
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            return await client.get("/health/ready")
    finally:
        await redis_client.aclose()


@pytest.mark.integration
async def test_b3_worker_readiness_answers_503_when_redis_is_down() -> None:
    """B-3: with nothing listening at the Redis URL, readiness answers 503 redis disconnected."""
    response = await request_worker_readiness(UNREACHABLE_REDIS_URL)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "connected", "redis": "disconnected"}


@pytest.mark.integration
async def test_b3_worker_readiness_answers_200_when_redis_answers() -> None:
    """B-3: with a real Redis at TEST_REDIS_URL, readiness answers 200 redis connected."""
    test_redis_url = os.environ.get("TEST_REDIS_URL")
    if not test_redis_url:
        pytest.skip("IAN-127: TEST_REDIS_URL is unset; this test needs a real Redis")

    response = await request_worker_readiness(test_redis_url)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected", "redis": "connected"}
