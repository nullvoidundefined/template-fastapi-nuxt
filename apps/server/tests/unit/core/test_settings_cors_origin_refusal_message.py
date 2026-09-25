"""A refused CORS_ORIGIN is named in the startup error, never echoed, and the port bounds hold.

An operator who pastes a URL carrying userinfo into CORS_ORIGIN has put a password in it, and the
startup error goes to the platform's log. Pydantic appends `input_value=...` to every validation
error by default, so the refusal must not repeat the value in its own message and the model must
hide the input.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL

# Joined at run time so no credential-shaped literal sits in the source (R-108).
USERINFO_MARKER = "-".join(["userinfo", "marker", "value"])


@pytest.fixture
def development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set only what Settings needs, so CORS_ORIGIN alone decides the outcome."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)


def build_settings_or_refusal() -> Settings | ValidationError:
    """Return the settings, or the refusal raised while building them."""
    try:
        return Settings(_env_file=None)
    except ValidationError as err:
        return err


@pytest.mark.usefixtures("development_environment")
def test_a_refused_origin_is_named_but_never_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal must say CORS_ORIGIN is wrong without writing the password into the log."""
    monkeypatch.setenv("CORS_ORIGIN", f"https://:{USERINFO_MARKER}@client.example")
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, ValidationError), "accepted an origin carrying userinfo"
    assert "CORS_ORIGIN" in str(outcome)
    assert USERINFO_MARKER not in str(outcome)


@pytest.mark.usefixtures("development_environment")
@pytest.mark.parametrize(
    "out_of_range_origin", ["https://client.example:65536", "https://client.example:0443"]
)
def test_a_port_outside_the_tcp_range_or_with_a_leading_zero_is_refused(
    monkeypatch: pytest.MonkeyPatch, out_of_range_origin: str
) -> None:
    """A browser never sends port 65536 or a zero-padded port, so neither may start the API."""
    monkeypatch.setenv("CORS_ORIGIN", out_of_range_origin)
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, ValidationError), f"accepted {out_of_range_origin!r}"
