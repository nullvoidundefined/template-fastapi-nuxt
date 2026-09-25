"""The API alone requires CORS_ORIGIN and FORWARDED_ALLOW_IPS; the worker and migrations do not.

The worker and `migrations/env.py` build the same `Settings` the API does, so a production check
on the shared model stopped both from starting in a deployment that, correctly, gives them only
the database and Redis values they use.
"""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, get_settings
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, clear_settings_cache

WORKER_REDIS_URL = "redis://redis.internal:6379/0"


@pytest.fixture
def worker_production_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give production only what the worker and migrations read, never the API-only values."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", WORKER_REDIS_URL)
    monkeypatch.delenv("CORS_ORIGIN", raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


def load_settings_or_refusal() -> Settings | ValidationError:
    """Return the process settings, or the refusal a production check raised while building them."""
    try:
        return get_settings()
    except ValidationError as err:
        return err


@pytest.mark.usefixtures("worker_production_environment")
def test_migrations_load_production_settings_without_api_only_values() -> None:
    """migrations/env.py reads only the database URL, so it must get one without the API values."""
    settings = load_settings_or_refusal()
    assert isinstance(settings, Settings), f"settings refused to load: {settings}"
    assert settings.database_url.get_secret_value() == UNREACHABLE_DATABASE_URL


@pytest.mark.usefixtures("worker_production_environment")
def test_worker_builds_its_queue_connection_without_api_only_values() -> None:
    """The worker's arq connection must come up in production with REDIS_URL alone."""
    settings = load_settings_or_refusal()
    assert isinstance(settings, Settings), f"settings refused to load: {settings}"
    # arq's WorkerSettings reads settings in its class body, so the module is imported only once
    # the settings it reads are known to load.
    from app.workers.settings import build_redis_settings  # noqa: PLC0415

    redis_settings = build_redis_settings(settings)
    assert (redis_settings.host, redis_settings.port, redis_settings.database) == (
        "redis.internal",
        6379,
        0,
    )


@pytest.mark.usefixtures("worker_production_environment")
def test_the_api_still_refuses_production_without_its_own_values() -> None:
    """Moving the check must not let the API itself start without CORS or proxy trust."""
    refusal = start_api_or_refusal()
    assert isinstance(refusal, RuntimeError), f"expected the API's refusal, got {refusal!r}"
    assert "missing: CORS_ORIGIN, FORWARDED_ALLOW_IPS" in str(refusal)


def start_api_or_refusal() -> Exception | None:
    """Build the API and return what refused it, or None when it started."""
    try:
        create_app()
    except (RuntimeError, ValidationError) as err:
        return err
    return None
