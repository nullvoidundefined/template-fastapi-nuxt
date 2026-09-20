"""Builds the FastAPI application; uvicorn runs `app.main:create_app` as a factory."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.constants.error_codes import ErrorCode
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.engine import create_database_engine
from app.errors import AppError, build_error_response
from app.middleware.request_context import RequestContextMiddleware, is_valid_request_id
from app.routers import health
from app.schemas.errors import ErrorResponse

REQUEST_ID_HEADER = "X-Request-Id"

logger = structlog.get_logger(__name__)

# Fixed messages, so a routing failure never echoes the path or method the client sent back at it.
ROUTING_CODES = {
    404: ErrorCode.ROUTING_NOT_FOUND,
    405: ErrorCode.ROUTING_METHOD_NOT_ALLOWED,
}
ROUTING_MESSAGES = {
    ErrorCode.ROUTING_NOT_FOUND: "The requested resource was not found",
    ErrorCode.ROUTING_METHOD_NOT_ALLOWED: "That method is not allowed on this resource",
    ErrorCode.SERVER_INTERNAL_ERROR: "The request could not be completed",
}
DATABASE_UNAVAILABLE_MESSAGE = "The database is unavailable"
INTERNAL_ERROR_MESSAGE = "Internal server error"
VALIDATION_ERROR_MESSAGE = "The request body failed validation"


def create_app() -> FastAPI:
    """Assemble settings, logging, the lifespan, middleware, and routers, in that order."""
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(
        title=settings.app_name,
        lifespan=build_lifespan(settings),
        # Documented on every route, because any route can answer either: a body that fails
        # validation, and an unexpected exception the outermost handler catches. This is what puts
        # the failure envelope into openapi.yaml and from there into @repo/api-types, so the
        # frontend's error handling is typed from the same source as the success bodies.
        responses={
            400: {"model": ErrorResponse, "description": "The request failed validation"},
            500: {"model": ErrorResponse, "description": "An unexpected error occurred"},
        },
    )
    register_middleware(app)
    register_exception_handlers(app, settings)
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


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Install the five handlers, so no response ever carries FastAPI's default `{ detail }`."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    for database_exception in (OperationalError, OSError):
        app.add_exception_handler(database_exception, handle_database_unavailable)
    app.add_exception_handler(Exception, build_unexpected_error_handler(settings))


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer an expected failure with the status and code the error itself carries."""
    app_error = cast(AppError, exc)
    return build_error_response(app_error.status_code, app_error.code, app_error.message)


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Answer Starlette's routing failures in the envelope, never echoing the requested path."""
    http_exception = cast(StarletteHTTPException, exc)
    code = ROUTING_CODES.get(http_exception.status_code, ErrorCode.SERVER_INTERNAL_ERROR)
    return build_error_response(http_exception.status_code, code, ROUTING_MESSAGES[code])


async def handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer 400 with the field errors summarized, so the client can name the bad input."""
    validation_error = cast(RequestValidationError, exc)
    return build_error_response(
        400, ErrorCode.INPUT_VALIDATION_ERROR, summarize_field_errors(validation_error)
    )


async def handle_database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Answer 503 when the database could not be reached, rather than a bare 500."""
    logger.warning("request_database_unavailable", exc_info=exc)
    return build_error_response(
        503, ErrorCode.SERVER_DATABASE_UNAVAILABLE, DATABASE_UNAVAILABLE_MESSAGE
    )


def build_unexpected_error_handler(
    settings: Settings,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Return the 500 handler, which reveals the exception's message outside production only."""

    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("request_unhandled_exception", exc_info=exc)
        message = (
            INTERNAL_ERROR_MESSAGE
            if settings.environment == "production"
            else f"{INTERNAL_ERROR_MESSAGE}: {exc}"
        )
        return build_error_response(500, ErrorCode.SERVER_INTERNAL_ERROR, message)

    return handle_unexpected_error


def summarize_field_errors(validation_error: RequestValidationError) -> str:
    """Join each field error as `location: message`, so the response names the offending field."""
    summaries = [
        f"{format_error_location(error['loc'])}: {error['msg']}"
        for error in validation_error.errors()
    ]
    return (
        f"{VALIDATION_ERROR_MESSAGE}: {'; '.join(summaries)}"
        if summaries
        else VALIDATION_ERROR_MESSAGE
    )


def format_error_location(location: Sequence[object]) -> str:
    """Render a Pydantic error location, dropping the leading `body` segment when present."""
    segments = [str(segment) for segment in location]
    if segments and segments[0] == "body":
        segments = segments[1:]
    return ".".join(segments) or "body"
