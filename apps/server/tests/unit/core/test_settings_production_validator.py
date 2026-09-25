"""The production API must reject incomplete security configuration before serving requests."""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, clear_settings_cache


@pytest.fixture
def production_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set every prerequisite without constructing Settings during fixture setup."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("CORS_ORIGIN", "https://client.example")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6380/0")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.usefixtures("production_environment")
@pytest.mark.parametrize("missing_value", ["CORS_ORIGIN", "REDIS_URL", "FORWARDED_ALLOW_IPS"])
@pytest.mark.parametrize("value", [None, "", " \t\n"], ids=["absent", "empty", "whitespace"])
def test_production_api_refuses_to_start_when_a_required_value_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing_value: str,
    value: str | None,
) -> None:
    """Each absent, empty, or whitespace-only value must prevent the production API starting."""
    if value is None:
        monkeypatch.delenv(missing_value)
    else:
        monkeypatch.setenv(missing_value, value)
    try:
        create_app()
    except (RuntimeError, ValidationError) as err:
        refusal: Exception | None = err
    else:
        refusal = None
    assert isinstance(refusal, RuntimeError), f"expected the API's refusal, got {refusal!r}"
    assert f"missing: {missing_value}" in str(refusal)


@pytest.mark.usefixtures("production_environment")
def test_production_constructs_and_retains_all_three_required_values() -> None:
    """Complete production configuration must be accepted and available to consumers."""
    settings = Settings(_env_file=None)
    assert getattr(settings, "cors_origin", None) == "https://client.example"
    assert getattr(settings, "forwarded_allow_ips", None) == "127.0.0.1"
    assert settings.redis_url is not None
    assert settings.redis_url.get_secret_value() == "redis://localhost:6380/0"
