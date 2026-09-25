"""Typed settings read from the environment once per process and validated at startup."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVIRONMENT = "production"
# Every one of these is a protection that silently degrades rather than failing loudly when it is
# absent, which is why production refuses to start without them instead of warning. Without
# CORS_ORIGIN the allowed-origin list is empty and the CSRF guard loses the preflight that makes
# its header meaningful; without REDIS_URL the rate limiter counts per process, so an attacker
# rotates across instances past the auth limit; without FORWARDED_ALLOW_IPS uvicorn keys every
# proxied request on the proxy's own address and the whole site shares one rate-limit bucket.
REQUIRED_PRODUCTION_FIELDS = ("cors_origin", "redis_url", "forwarded_allow_ips")
REQUIRED_PRODUCTION_VARIABLES = "CORS_ORIGIN, REDIS_URL, and FORWARDED_ALLOW_IPS"
UNSAFE_CORS_ORIGINS = frozenset({"*", "null"})


class Settings(BaseSettings):
    """Every environment variable the API reads, with its type and default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "template-fastapi-nuxt"
    environment: Literal["development", "test", "staging", "production"] = "development"
    # Each integration below is optional: without its values the client logs one warning at
    # startup and does nothing, so development and tests run without the provider.
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = 0.0
    posthog_api_key: SecretStr | None = None
    posthog_host: str = "https://us.i.posthog.com"
    r2_account_id: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    database_url: SecretStr
    database_ca_cert: str | None = None
    redis_url: SecretStr | None = None
    cors_origin: str | None = None
    forwarded_allow_ips: str | None = None
    # WORKER_PORT when set, as under compose; otherwise the PORT a platform such as Railway
    # injects and health-checks, so the worker's probes answer where the platform looks.
    worker_port: int = Field(default=3002, validation_alias=AliasChoices("WORKER_PORT", "PORT"))
    # The web origin the reset-email link and the Stripe redirect URLs are built from.
    client_url: str = "http://localhost:3000"
    # Without a key the worker logs each email instead of sending it, so development and tests
    # run without the provider.
    resend_api_key: SecretStr | None = None
    email_from: str = "Template <noreply@example.test>"
    # Billing is optional in every environment, production included, so a deployment that has
    # not set up Stripe still starts. The absence is loud where it matters instead: without the
    # key the checkout and portal routes answer 503 `BILLING_NOT_CONFIGURED`, and without the
    # signing secret every webhook delivery answers 400 `BILLING_WEBHOOK_MISCONFIGURED`, which
    # Stripe's dashboard shows as failing deliveries.
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    # Replaces https://api.stripe.com, so the end-to-end stack can point the SDK at stripe-mock.
    stripe_api_base: str | None = None

    @field_validator("stripe_secret_key", "stripe_webhook_secret", "stripe_api_base", mode="after")
    @classmethod
    def treat_blank_stripe_value_as_unset(
        cls, value: SecretStr | str | None
    ) -> SecretStr | str | None:
        """Read an empty Stripe variable as unset, so billing reports itself unconfigured.

        docker-compose passes `STRIPE_SECRET_KEY: ${STRIPE_SECRET_KEY:-}` through as an empty
        string when the host has none, and an empty key would otherwise build a client whose
        every call Stripe refuses, answering 500 where 503 `BILLING_NOT_CONFIGURED` is the truth.
        """
        return None if is_blank(value) else value

    @field_validator("cors_origin", mode="after")
    @classmethod
    def refuse_unsafe_cors_origin(cls, value: str | None) -> str | None:
        """Refuse a CORS origin that opens the credentialed API to every site, in any environment.

        Starlette reads `*` as allow-all and, with credentials on, echoes each caller's Origin, and
        `null` is the Origin every sandboxed iframe and file:// page sends. Either one hands the
        session cookie's single-origin boundary to the whole web, so no stack may start with it.
        """
        if value is not None and value.strip().lower() in UNSAFE_CORS_ORIGINS:
            raise ValueError(f"CORS_ORIGIN must name one concrete origin, not {value.strip()!r}")
        return value

    @model_validator(mode="after")
    def require_production_values(self) -> Self:
        """Refuse to start in production without the values production's protections need."""
        if self.environment != PRODUCTION_ENVIRONMENT:
            return self
        missing = [name for name in REQUIRED_PRODUCTION_FIELDS if is_blank(getattr(self, name))]
        if missing:
            raise ValueError(
                f"{REQUIRED_PRODUCTION_VARIABLES} are required in production; missing: "
                f"{', '.join(name.upper() for name in missing)}"
            )
        return self


def is_blank(value: SecretStr | str | None) -> bool:
    """Return True when the value is absent, empty, or only whitespace.

    An unset variable and one exported as an empty string mean the same thing to an operator, and
    a shell exports an empty string easily (`CORS_ORIGIN=` in an env file, a substitution that
    resolved to nothing). Checking only for None would let production start with an empty allowed
    origin list, which is the configuration the validator exists to refuse.
    """
    if value is None:
        return True
    text = value.get_secret_value() if isinstance(value, SecretStr) else value
    return not text.strip()


@lru_cache
def get_settings() -> Settings:
    """Build the settings once per process; tests clear the cache to re-read the environment."""
    return Settings()
