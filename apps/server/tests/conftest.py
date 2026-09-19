"""Shared fixtures: the app under test, an HTTP client that runs its lifespan, and log capture.

The app is built through the public factory `app.main.create_app()` after the environment is
set, so every test exercises the same assembly uvicorn runs. The default database URL points at a
closed local port, so any test that does not override `database_url` proves it never needs a
reachable Postgres.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import structlog
from fastapi import FastAPI

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
TEST_BASE_URL = "http://testserver"


@pytest.fixture
def database_url() -> str:
    """Return the database URL the app under test reads from DATABASE_URL."""
    return UNREACHABLE_DATABASE_URL


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next get_settings() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415 (missing until implemented)

    get_settings.cache_clear()


@pytest.fixture
def server_app(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    """Build the app through create_app() with DATABASE_URL and ENVIRONMENT patched."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    from app.main import create_app  # noqa: PLC0415 (missing until implemented)

    clear_settings_cache()
    application = create_app()
    yield application
    clear_settings_cache()


@pytest.fixture
async def api_client(server_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's lifespan, so the engine exists, and yield a client bound to the app."""
    async with server_app.router.lifespan_context(server_app):
        transport = httpx.ASGITransport(app=server_app)
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            yield client


@pytest.fixture
def captured_log_events(server_app: FastAPI) -> Iterator[list[dict[str, Any]]]:
    """Record every structlog event after the app's own processors run, up to the renderer.

    The recorder is spliced into the processor chain that create_app() configured, just before
    the final renderer, so the captured event dict holds exactly what the configured chain
    (including any context merging) produced for that line.
    """
    original_config = structlog.get_config()
    configured_processors = list(original_config["processors"])
    assert configured_processors, "create_app() must configure a structlog processor chain"
    recorded_events: list[dict[str, Any]] = []

    def record_event_dict(
        _logger: object, _method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        recorded_events.append(dict(event_dict))
        return event_dict

    structlog.configure(
        processors=[*configured_processors[:-1], record_event_dict, configured_processors[-1]],
        cache_logger_on_first_use=False,
    )
    yield recorded_events
    structlog.configure(**original_config)
