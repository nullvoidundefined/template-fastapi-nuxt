"""Production must reject incomplete security configuration before serving requests."""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL


@pytest.fixture
def production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set every prerequisite without constructing Settings during fixture setup."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("CORS_ORIGIN", "https://client.example")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6380/0")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")


@pytest.mark.usefixtures("production_environment")
@pytest.mark.parametrize("missing_value", ["CORS_ORIGIN", "REDIS_URL", "FORWARDED_ALLOW_IPS"])
@pytest.mark.parametrize("value", [None, "", " \t\n"], ids=["absent", "empty", "whitespace"])
def test_production_refuses_to_construct_when_a_required_value_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing_value: str,
    value: str | None,
) -> None:
    """Each absent, empty, or whitespace-only value must prevent production startup."""
    if value is None:
        monkeypatch.delenv(missing_value)
    else:
        monkeypatch.setenv(missing_value, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("production_environment")
def test_production_constructs_and_retains_all_three_required_values() -> None:
    """Complete production configuration must be accepted and available to consumers."""
    settings = Settings(_env_file=None)
    assert getattr(settings, "cors_origin", None) == "https://client.example"
    assert getattr(settings, "forwarded_allow_ips", None) == "127.0.0.1"
    assert settings.redis_url is not None
    assert settings.redis_url.get_secret_value() == "redis://localhost:6380/0"
