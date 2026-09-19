"""B-1 unit tests for the health router with Postgres unreachable or hanging.

The shared `database_url` fixture points DATABASE_URL at a closed local port, so liveness must
answer without any dependency and readiness must report the database as disconnected with 503.
The readiness deadline test swaps in an engine whose connect never finishes, so the probe must
give up on its own bound rather than wait for the driver's connect timeout.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

HANGING_CONNECT_SECONDS = 60
READINESS_DEADLINE_SECONDS = 5


class HangingEngine:
    """Engine stand-in whose connect() sleeps far past any readiness bound."""

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[None]:
        await asyncio.sleep(HANGING_CONNECT_SECONDS)
        yield

    async def dispose(self) -> None:
        return None


@pytest.fixture
def hanging_engine_app(server_app: FastAPI, api_client: httpx.AsyncClient) -> Iterator[FastAPI]:
    """Swap the started app's engine for a hanging one, restoring the real engine afterwards."""
    real_engine = server_app.state.engine
    server_app.state.engine = HangingEngine()
    yield server_app
    server_app.state.engine = real_engine


async def test_b1_liveness_answers_200_ok_while_postgres_is_unreachable(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: GET /health answers 200 {"status": "ok"} without touching a dependency."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_b1_readiness_answers_503_degraded_when_postgres_is_unreachable(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: GET /health/ready answers 503 with db disconnected when the engine cannot connect."""
    response = await api_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "disconnected"}


async def test_b1_liveness_still_answers_200_after_a_failed_readiness_probe(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: a failed readiness connect leaves liveness untouched on the next request."""
    readiness_response = await api_client.get("/health/ready")
    liveness_response = await api_client.get("/health")

    assert readiness_response.status_code == 503
    assert liveness_response.status_code == 200
    assert liveness_response.json() == {"status": "ok"}


async def test_defect3_b1_readiness_answers_503_within_its_deadline_when_connect_hangs(
    hanging_engine_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Defect 3, B-1: a hanging database connect still yields 503 degraded within 5 seconds."""
    async with asyncio.timeout(READINESS_DEADLINE_SECONDS):
        response = await api_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "disconnected"}
