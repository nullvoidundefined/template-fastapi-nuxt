"""CORS_ORIGIN must name one concrete origin, never a value CORSMiddleware reads as allow-all."""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL

# Starlette treats "*" as allow_all_origins and, with credentials on, echoes any caller's Origin
# back; "null" is the Origin a sandboxed iframe or a file:// page sends, so either one hands the
# session cookie's credential boundary to every site on the web.
UNSAFE_ORIGINS = ["*", " * ", "null", "NULL", " null "]


@pytest.fixture
def complete_production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set every production prerequisite, so only CORS_ORIGIN decides the outcome."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6380/0")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")


@pytest.mark.usefixtures("complete_production_environment")
@pytest.mark.parametrize("unsafe_origin", UNSAFE_ORIGINS)
def test_production_refuses_a_wildcard_or_null_cors_origin(
    monkeypatch: pytest.MonkeyPatch, unsafe_origin: str
) -> None:
    """Production must not start with an origin that disables the single-origin boundary."""
    monkeypatch.setenv("CORS_ORIGIN", unsafe_origin)
    with pytest.raises(ValidationError, match="CORS_ORIGIN"):
        Settings(_env_file=None)


@pytest.mark.parametrize("environment", ["development", "test", "staging"])
@pytest.mark.parametrize("unsafe_origin", UNSAFE_ORIGINS)
def test_every_environment_refuses_a_wildcard_or_null_cors_origin(
    monkeypatch: pytest.MonkeyPatch, environment: str, unsafe_origin: str
) -> None:
    """A staging or local stack with a wildcard is as open as production, so none may start."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("CORS_ORIGIN", unsafe_origin)
    with pytest.raises(ValidationError, match="CORS_ORIGIN"):
        Settings(_env_file=None)


@pytest.mark.usefixtures("complete_production_environment")
def test_production_accepts_one_concrete_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The validator must not refuse the configuration production actually runs with."""
    monkeypatch.setenv("CORS_ORIGIN", "https://client.example")
    assert Settings(_env_file=None).cors_origin == "https://client.example"
