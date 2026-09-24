"""B-3 unit tests for the two settings the worker adds: REDIS_URL and WORKER_PORT.

The API must keep starting with REDIS_URL unset, so the field is optional; WORKER_PORT defaults
to 3002, the port the workspace reserves for worker health.
"""

from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from tests.conftest import UNREACHABLE_DATABASE_URL, clear_settings_cache

WORKER_REDIS_URL = "redis://127.0.0.1:6390/2"
DEFAULT_WORKER_PORT = 3002
CONFIGURED_WORKER_PORT = 4102
MISSING_FIELD = object()


@pytest.fixture
def settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start from DATABASE_URL only, with the cached settings cleared before and after."""
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("WORKER_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.usefixtures("settings_environment")
def test_b3_settings_default_to_no_redis_url_and_worker_port_3002() -> None:
    """B-3: with REDIS_URL and WORKER_PORT unset, redis_url is None and worker_port is 3002."""
    from app.core.settings import get_settings  # noqa: PLC0415

    settings = get_settings()
    redis_url = getattr(settings, "redis_url", MISSING_FIELD)
    worker_port = getattr(settings, "worker_port", MISSING_FIELD)

    assert redis_url is not MISSING_FIELD, "Settings must declare redis_url"
    assert redis_url is None
    assert worker_port == DEFAULT_WORKER_PORT


@pytest.mark.usefixtures("settings_environment")
def test_b3_settings_read_redis_url_as_a_secret_and_worker_port_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-3: REDIS_URL is held as a secret (never printed) and WORKER_PORT is parsed as an int."""
    monkeypatch.setenv("REDIS_URL", WORKER_REDIS_URL)
    monkeypatch.setenv("WORKER_PORT", str(CONFIGURED_WORKER_PORT))
    from app.core.settings import get_settings  # noqa: PLC0415

    settings = get_settings()
    redis_url = getattr(settings, "redis_url", MISSING_FIELD)
    worker_port = getattr(settings, "worker_port", MISSING_FIELD)

    assert redis_url is not MISSING_FIELD, "Settings must declare redis_url"
    assert isinstance(redis_url, SecretStr)
    assert redis_url.get_secret_value() == WORKER_REDIS_URL
    assert WORKER_REDIS_URL not in repr(settings)
    assert worker_port == CONFIGURED_WORKER_PORT


RAILWAY_INJECTED_PORT = 7311


@pytest.mark.usefixtures("settings_environment")
def test_b3_the_worker_listens_on_the_platform_port_when_worker_port_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Railway injects PORT and health-checks it, so the probes must answer there by default."""
    monkeypatch.setenv("PORT", str(RAILWAY_INJECTED_PORT))
    from app.core.settings import get_settings  # noqa: PLC0415

    assert get_settings().worker_port == RAILWAY_INJECTED_PORT


@pytest.mark.usefixtures("settings_environment")
def test_b3_an_explicit_worker_port_wins_over_the_platform_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WORKER_PORT still decides when it is set, as it is under compose."""
    monkeypatch.setenv("PORT", str(RAILWAY_INJECTED_PORT))
    monkeypatch.setenv("WORKER_PORT", str(CONFIGURED_WORKER_PORT))
    from app.core.settings import get_settings  # noqa: PLC0415

    assert get_settings().worker_port == CONFIGURED_WORKER_PORT
