"""Builds the one async SQLAlchemy engine each API process uses.

Deployed environments (staging and production) connect to Postgres over TLS with the server
certificate verified and the hostname checked, the asyncpg form of `sslmode=verify-full`; a
private certificate authority can be trusted through `DATABASE_CA_CERT`. Local development and
tests connect without TLS, because a local Postgres has none.
"""

import ssl
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.settings import Settings

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = "10000"
TLS_ENVIRONMENTS = frozenset({"staging", "production"})


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the engine with a bounded pool and the connect arguments for this environment."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=10,
        max_overflow=5,
        pool_timeout=5,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args=build_connect_args(settings),
    )


def build_connect_args(settings: Settings) -> dict[str, Any]:
    """Return asyncpg's connect arguments: timeouts always, verified TLS when deployed."""
    connect_args: dict[str, Any] = {
        "timeout": CONNECT_TIMEOUT_SECONDS,
        "server_settings": {"statement_timeout": STATEMENT_TIMEOUT_MILLISECONDS},
    }
    if settings.environment in TLS_ENVIRONMENTS:
        connect_args["ssl"] = build_verified_tls_context(settings.database_ca_cert)
    return connect_args


def build_verified_tls_context(ca_cert_path: str | None) -> ssl.SSLContext:
    """Return a context that requires a valid certificate and a matching hostname."""
    context = ssl.create_default_context(cafile=ca_cert_path)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
