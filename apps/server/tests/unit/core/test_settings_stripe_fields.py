"""Slice 06 unit tests for the Stripe settings: two secrets and the optional API base.

Both secrets are optional in every environment, production included: a deployment that has not
set up billing still starts, its billing routes answer 503 `BILLING_NOT_CONFIGURED`, and its
webhook answers 400 `BILLING_WEBHOOK_MISCONFIGURED`, so the absence is loud at the route rather
than fatal to the whole API. Each secret is a `SecretStr`, so neither can reach a log line.
"""

from collections.abc import Iterator

import pytest

from tests.conftest import STRIPE_TEST_API_KEY, UNREACHABLE_DATABASE_URL, clear_settings_cache

WEBHOOK_SIGNING_VALUE = "_".join(("whsec", "unit", "placeholder"))
STRIPE_MOCK_BASE = "http://stripe-mock:12111"
MISSING_FIELD = object()
STRIPE_VARIABLES = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_API_BASE")


@pytest.fixture
def settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start from DATABASE_URL only, with every Stripe variable unset and the cache cleared."""
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    for name in STRIPE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.usefixtures("settings_environment")
def test_stripe_settings_default_to_absent() -> None:
    """With no Stripe variable set, the key, the webhook secret, and the API base are all None."""
    from app.core.settings import get_settings  # noqa: PLC0415

    settings = get_settings()

    assert getattr(settings, "stripe_secret_key", MISSING_FIELD) is None
    assert getattr(settings, "stripe_webhook_secret", MISSING_FIELD) is None
    assert getattr(settings, "stripe_api_base", MISSING_FIELD) is None


@pytest.mark.usefixtures("settings_environment")
def test_stripe_secrets_are_read_as_secrets_that_never_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both secrets are read from the environment and neither appears in the settings repr."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", STRIPE_TEST_API_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SIGNING_VALUE)
    monkeypatch.setenv("STRIPE_API_BASE", STRIPE_MOCK_BASE)
    from app.core.settings import get_settings  # noqa: PLC0415

    settings = get_settings()

    assert getattr(settings, "stripe_secret_key", None) is not None
    assert getattr(settings, "stripe_webhook_secret", None) is not None
    assert settings.stripe_secret_key.get_secret_value() == STRIPE_TEST_API_KEY
    assert settings.stripe_webhook_secret.get_secret_value() == WEBHOOK_SIGNING_VALUE
    assert settings.stripe_api_base == STRIPE_MOCK_BASE
    assert STRIPE_TEST_API_KEY not in repr(settings)
    assert WEBHOOK_SIGNING_VALUE not in repr(settings)


@pytest.mark.usefixtures("settings_environment")
def test_production_starts_without_stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Billing is optional in production: the validator does not require either secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGIN", "https://client.example.test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    from app.core.settings import get_settings  # noqa: PLC0415

    settings = get_settings()

    assert settings.environment == "production"
    assert getattr(settings, "stripe_secret_key", MISSING_FIELD) is None
    assert getattr(settings, "stripe_webhook_secret", MISSING_FIELD) is None
