"""B-14 unit tests for the API's job queue: how it is built, provided, and refused without Redis.

The queue is built in the lifespan and must not connect there. The rate limiter treats a Redis
outage as something the API survives, and an application whose startup pinged Redis would refuse
to start during exactly that outage, taking every route down with the four it was meant to cost.
"""

import pytest
from fastapi import FastAPI

from tests.conftest import UNREACHABLE_DATABASE_URL, clear_settings_cache

UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


def build_application(monkeypatch: pytest.MonkeyPatch, redis_url: str | None) -> FastAPI:
    """Build the real application with or without REDIS_URL."""
    from app.main import create_app  # noqa: PLC0415

    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "test")
    if redis_url is None:
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        monkeypatch.setenv("REDIS_URL", redis_url)
    clear_settings_cache()
    return create_app()


async def test_b14_the_lifespan_builds_an_arq_queue_without_connecting_to_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable Redis does not stop startup, and the queue is arq's own client."""
    from arq.connections import ArqRedis  # noqa: PLC0415

    application = build_application(monkeypatch, UNREACHABLE_REDIS_URL)

    async with application.router.lifespan_context(application):
        job_queue = getattr(application.state, "job_queue", None)
        assert isinstance(job_queue, ArqRedis)
    clear_settings_cache()


async def test_b14_without_redis_the_queue_refuses_to_enqueue_with_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With REDIS_URL unset, enqueueing raises an error that names the missing variable."""
    application = build_application(monkeypatch, None)

    async with application.router.lifespan_context(application):
        job_queue = getattr(application.state, "job_queue", None)
        assert job_queue is not None
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            await job_queue.enqueue_job("send_password_reset_email", "reader@example.test")
    clear_settings_cache()


def test_b14_get_job_queue_returns_the_queue_the_lifespan_stored() -> None:
    """The dependency hands a route the one queue on the application's state."""
    from starlette.requests import Request  # noqa: PLC0415

    from app.dependencies.job_queue import get_job_queue  # noqa: PLC0415

    application = FastAPI()
    stored_queue = object()
    application.state.job_queue = stored_queue
    request = Request({"type": "http", "app": application})

    assert get_job_queue(request) is stored_queue
