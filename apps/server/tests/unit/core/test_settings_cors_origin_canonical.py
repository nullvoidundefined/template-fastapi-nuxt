"""CORS_ORIGIN must be written exactly as a browser serializes an Origin header, or be unset.

A browser sends the scheme and host in lowercase, never userinfo, and leaves out the scheme's
default port. CORSMiddleware compares that header to the configured string byte for byte, so any
other spelling of the same site starts the API with every credentialed preflight failing.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL

# Joined at run time so no credential-shaped literal sits in the source (R-108).
USERINFO_ORIGIN = "https://:" + "-".join(["userinfo", "value"]) + "@client.example"
NON_CANONICAL_ORIGINS = [
    USERINFO_ORIGIN,
    "https://@client.example",
    "https://a.example b.example",
    "https://client.exa\tmple",
    "HTTPS://Client.Example",
    "https://client.example:443",
    "http://client.example:80",
    "https://client.example:",
    "https://client.example\\evil",
]


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
@pytest.mark.parametrize("non_canonical_origin", NON_CANONICAL_ORIGINS)
def test_an_origin_a_browser_would_never_send_is_refused(
    monkeypatch: pytest.MonkeyPatch, non_canonical_origin: str
) -> None:
    """Only the serialization a browser produces may start the API."""
    monkeypatch.setenv("CORS_ORIGIN", non_canonical_origin)
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, ValidationError), f"accepted {non_canonical_origin!r}"
    assert "CORS_ORIGIN" in str(outcome)


@pytest.mark.usefixtures("development_environment")
def test_a_whitespace_only_origin_is_read_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank value must mean no allowed origin, never an allow list holding whitespace."""
    monkeypatch.setenv("CORS_ORIGIN", "   ")
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, Settings), f"refused a blank origin: {outcome}"
    assert outcome.cors_origin is None


@pytest.mark.usefixtures("development_environment")
@pytest.mark.parametrize(
    "canonical_origin",
    ["https://client.example:8443", "http://localhost:3000", "https://app.client-example.test"],
)
def test_a_canonical_origin_with_a_non_default_port_is_accepted(
    monkeypatch: pytest.MonkeyPatch, canonical_origin: str
) -> None:
    """The stricter check must still accept the origins compose and deployments use."""
    monkeypatch.setenv("CORS_ORIGIN", canonical_origin)
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, Settings), f"refused {canonical_origin!r}: {outcome}"
    assert outcome.cors_origin == canonical_origin
