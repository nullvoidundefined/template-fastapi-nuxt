"""Typed settings read from the environment once per process and validated at startup."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every environment variable the API reads, with its type and default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "template-fastapi-nuxt"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: SecretStr
    database_ca_cert: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Build the settings once per process; tests clear the cache to re-read the environment."""
    return Settings()
