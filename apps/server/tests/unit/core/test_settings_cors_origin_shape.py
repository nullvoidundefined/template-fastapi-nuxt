"""CORS_ORIGIN must be one bare http(s) origin, the only shape a browser's Origin header matches.

CORSMiddleware compares the header to the configured string exactly, so a value with a path, a
trailing slash, a list, a pattern, or no scheme never matches any request. The API would start and
every credentialed browser call would then fail its preflight, with nothing at startup to say why.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL

MALFORMED_ORIGINS = [
    "client.example",
    "https://client.example/",
    "https://client.example/app",
    "https://a.example,https://b.example",
    "https://*.example",
    "ftp://client.example",
    "https://client.example?next=1",
    "https://client.example#top",
    "https://user@client.example",
    "https://",
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
@pytest.mark.parametrize("malformed_origin", MALFORMED_ORIGINS)
def test_a_cors_origin_that_no_browser_origin_can_match_is_refused(
    monkeypatch: pytest.MonkeyPatch, malformed_origin: str
) -> None:
    """Anything but scheme://host[:port] must stop startup instead of breaking CORS silently."""
    monkeypatch.setenv("CORS_ORIGIN", malformed_origin)
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, ValidationError), f"accepted {malformed_origin!r}"
    assert "CORS_ORIGIN" in str(outcome)


@pytest.mark.usefixtures("development_environment")
@pytest.mark.parametrize("bare_origin", ["https://client.example", "http://localhost:3000"])
def test_a_bare_origin_is_accepted_unchanged(
    monkeypatch: pytest.MonkeyPatch, bare_origin: str
) -> None:
    """The shape check must not refuse the origins deployments and compose actually use."""
    monkeypatch.setenv("CORS_ORIGIN", bare_origin)
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, Settings), f"refused {bare_origin!r}: {outcome}"
    assert outcome.cors_origin == bare_origin


@pytest.mark.usefixtures("development_environment")
def test_a_bare_origin_is_stored_without_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The middleware must receive exactly the string a browser's Origin header carries."""
    monkeypatch.setenv("CORS_ORIGIN", "  https://client.example \n")
    outcome = build_settings_or_refusal()
    assert isinstance(outcome, Settings), f"refused a padded origin: {outcome}"
    assert outcome.cors_origin == "https://client.example"
