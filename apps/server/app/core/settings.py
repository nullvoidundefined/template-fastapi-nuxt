"""Typed settings read from the environment once per process and validated at startup."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
    # The web origin the reset-email link is built from, and later the Stripe redirect URLs.
    client_url: str = "http://localhost:3000"
    # Without a key the worker logs each email instead of sending it, so development and tests
    # run without the provider.
    resend_api_key: SecretStr | None = None
    email_from: str = "Template <noreply@example.test>"

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
