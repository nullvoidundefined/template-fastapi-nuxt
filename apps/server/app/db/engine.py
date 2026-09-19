"""Builds the one async SQLAlchemy engine each API process uses."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.settings import Settings

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = "10000"


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the engine with a bounded pool, a connect timeout, and a statement timeout."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=10,
        max_overflow=5,
        pool_timeout=5,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={
            "timeout": CONNECT_TIMEOUT_SECONDS,
            "server_settings": {"statement_timeout": STATEMENT_TIMEOUT_MILLISECONDS},
        },
    )
