"""B-3 unit tests for the worker's probe app in app/workers/health.py (R-345).

The app comes from `create_worker_health_app(engine, redis)` and is driven in-process through
httpx's ASGITransport, with fake engine and fake Redis objects standing in for the dependencies.
Liveness must never touch either dependency; readiness must report each dependency on its own,
answering 503 degraded with the failing component(s) set to "disconnected", and must give up on
a hanging dependency at the module's READINESS_TIMEOUT_SECONDS deadline.

The module under test, and redis itself, are imported inside each test so that a missing module
fails every test individually instead of failing collection.
"""

import asyncio
import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any, cast

import httpx
import pytest

WORKER_HEALTH_MODULE = "app.workers.health"
TEST_BASE_URL = "http://worker-health"
HANGING_SECONDS = 60
PATCHED_READINESS_TIMEOUT_SECONDS = 0.1
TEST_DEADLINE_SECONDS = 2


def import_worker_health_module() -> ModuleType:
    """Import app.workers.health, the unit under test."""
    return importlib.import_module(WORKER_HEALTH_MODULE)


class FakeConnection:
    """Connection stand-in whose execute() records the statement and succeeds."""

    def __init__(self, executed_statements: list[str]) -> None:
        self.executed_statements = executed_statements

    async def execute(self, statement: Any) -> None:
        self.executed_statements.append(str(statement))


class FakeEngine:
    """Engine stand-in: connects and runs statements, or raises, or hangs, on connect()."""

    def __init__(self, connect_error: BaseException | None = None, is_hanging: bool = False):
        self.connect_error = connect_error
        self.is_hanging = is_hanging
        self.connect_attempts = 0
        self.executed_statements: list[str] = []

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeConnection]:
        self.connect_attempts += 1
        if self.is_hanging:
            await asyncio.sleep(HANGING_SECONDS)
        if self.connect_error is not None:
            raise self.connect_error
        yield FakeConnection(self.executed_statements)

    async def dispose(self) -> None:
        return None


class FakeRedis:
    """Redis client stand-in: ping() answers True, or raises, or hangs."""

    def __init__(self, ping_error: BaseException | None = None, is_hanging: bool = False):
        self.ping_error = ping_error
        self.is_hanging = is_hanging
        self.ping_attempts = 0

    async def ping(self) -> bool:
        self.ping_attempts += 1
        if self.is_hanging:
            await asyncio.sleep(HANGING_SECONDS)
        if self.ping_error is not None:
            raise self.ping_error
        return True


def build_redis_connection_error() -> Exception:
    """Return the error redis-py raises when the server cannot be reached."""
    redis_exceptions = importlib.import_module("redis.exceptions")
    # importlib.import_module returns ModuleType, so attribute access types as Any.
    return cast(
        Exception, redis_exceptions.ConnectionError("Error 61 connecting to 127.0.0.1:6379.")
    )


async def request_worker_probe(
    health_module: ModuleType, engine: FakeEngine, redis_client: FakeRedis, path: str
) -> httpx.Response:
    """Build the worker probe app around the fakes and send one GET to it."""
    probe_app = health_module.create_worker_health_app(engine, redis_client)
    transport = httpx.ASGITransport(app=probe_app)
    async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
        return await client.get(path)


async def test_b3_worker_liveness_answers_200_without_touching_either_dependency() -> None:
    """B-3: GET /health answers 200 {"status": "ok"} even when both dependencies would fail."""
    health_module = import_worker_health_module()
    failing_engine = FakeEngine(connect_error=OSError("connection refused"))
    failing_redis = FakeRedis(ping_error=build_redis_connection_error())

    response = await request_worker_probe(health_module, failing_engine, failing_redis, "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert failing_engine.connect_attempts == 0
    assert failing_redis.ping_attempts == 0


async def test_b3_worker_readiness_answers_200_when_postgres_and_redis_answer() -> None:
    """B-3: GET /health/ready answers 200 with db and redis connected when both answer."""
    health_module = import_worker_health_module()
    healthy_engine = FakeEngine()
    healthy_redis = FakeRedis()

    response = await request_worker_probe(
        health_module, healthy_engine, healthy_redis, "/health/ready"
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected", "redis": "connected"}
    assert healthy_engine.executed_statements == ["SELECT 1"]


async def test_b3_worker_readiness_answers_503_redis_disconnected_when_ping_fails() -> None:
    """B-3: a Redis ConnectionError from ping() yields 503 with only redis disconnected."""
    health_module = import_worker_health_module()
    failing_redis = FakeRedis(ping_error=build_redis_connection_error())

    response = await request_worker_probe(
        health_module, FakeEngine(), failing_redis, "/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "connected", "redis": "disconnected"}


async def test_b3_worker_readiness_answers_503_db_disconnected_when_connect_fails() -> None:
    """B-3: an OSError from the engine's connect yields 503 with only db disconnected."""
    health_module = import_worker_health_module()
    failing_engine = FakeEngine(connect_error=OSError("connection refused"))

    response = await request_worker_probe(
        health_module, failing_engine, FakeRedis(), "/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "disconnected", "redis": "connected"}


async def test_b3_worker_readiness_reports_both_disconnected_when_both_fail() -> None:
    """B-3: when both dependencies fail, both are probed and both are reported disconnected."""
    health_module = import_worker_health_module()
    failing_engine = FakeEngine(connect_error=OSError("connection refused"))
    failing_redis = FakeRedis(ping_error=build_redis_connection_error())

    response = await request_worker_probe(
        health_module, failing_engine, failing_redis, "/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "db": "disconnected",
        "redis": "disconnected",
    }


async def test_b3_worker_readiness_answers_503_within_its_deadline_when_ping_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-3: a Redis ping that never returns yields 503 redis disconnected at the deadline."""
    health_module = import_worker_health_module()
    monkeypatch.setattr(
        health_module, "READINESS_TIMEOUT_SECONDS", PATCHED_READINESS_TIMEOUT_SECONDS
    )
    hanging_redis = FakeRedis(is_hanging=True)

    async with asyncio.timeout(TEST_DEADLINE_SECONDS):
        response = await request_worker_probe(
            health_module, FakeEngine(), hanging_redis, "/health/ready"
        )

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "connected", "redis": "disconnected"}


async def test_b3_worker_readiness_answers_503_within_its_deadline_when_connect_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-3: a database connect that never finishes yields 503 db disconnected at the deadline."""
    health_module = import_worker_health_module()
    monkeypatch.setattr(
        health_module, "READINESS_TIMEOUT_SECONDS", PATCHED_READINESS_TIMEOUT_SECONDS
    )
    hanging_engine = FakeEngine(is_hanging=True)

    async with asyncio.timeout(TEST_DEADLINE_SECONDS):
        response = await request_worker_probe(
            health_module, hanging_engine, FakeRedis(), "/health/ready"
        )

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "disconnected", "redis": "connected"}
