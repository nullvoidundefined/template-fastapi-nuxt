"""Builds the FastAPI application; uvicorn runs `app.main:create_app` as a factory."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.engine import create_database_engine
from app.middleware.request_context import RequestContextMiddleware, is_valid_request_id
from app.routers import health

REQUEST_ID_HEADER = "X-Request-Id"


def create_app() -> FastAPI:
    """Assemble settings, logging, the lifespan, middleware, and routers, in that order."""
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title=settings.app_name, lifespan=build_lifespan(settings))
    register_middleware(app)
    app.include_router(health.router)
    return app


def build_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Return a lifespan that opens the engine on startup and disposes it on shutdown."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_database_engine(settings)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    return lifespan


def register_middleware(app: FastAPI) -> None:
    """Add middleware innermost first, so asgi-correlation-id wraps everything, 413s included."""
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=REQUEST_ID_HEADER,
        validator=is_valid_request_id,
    )
