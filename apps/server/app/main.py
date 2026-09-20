"""Builds the FastAPI application; uvicorn runs `app.main:create_app` as a factory."""

import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

import asyncpg
import structlog
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
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
HTTP_EXCEPTION_CODES = {
    400: ErrorCode.INPUT_VALIDATION_ERROR,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.CSRF_HEADER_MISSING,
    404: ErrorCode.ROUTING_NOT_FOUND,
    405: ErrorCode.ROUTING_METHOD_NOT_ALLOWED,
}
HTTP_EXCEPTION_MESSAGES = {
    ErrorCode.INPUT_VALIDATION_ERROR: "The request could not be read",
    ErrorCode.AUTH_REQUIRED: "Authentication is required",
    ErrorCode.CSRF_HEADER_MISSING: "That request is not allowed",
    ErrorCode.ROUTING_NOT_FOUND: "The requested resource was not found",
    ErrorCode.ROUTING_METHOD_NOT_ALLOWED: "That method is not allowed on this resource",
    ErrorCode.SERVER_INTERNAL_ERROR: "The request could not be completed",
}
# A lost connection reaches the handler as one of these. `OperationalError` is what the track
# names, but the asyncpg dialect wraps a mid-request disconnect as a plain `DBAPIError`, and a
# refused connect arrives as a bare `ConnectionRefusedError`, so all three shapes are registered.
# `OSError` itself is deliberately not: `TimeoutError` and `FileNotFoundError` are subclasses, and
# labelling a provider's timeout a database outage would answer the wrong code and log it as a
# warning rather than an error.
CONNECTION_ERROR_TYPES = (OperationalError, ConnectionError, socket.gaierror)
ASYNCPG_CONNECTION_ERRORS = (
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.InterfaceError,
)
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
    unexpected_error_handler = build_unexpected_error_handler(settings)
    for connection_error in CONNECTION_ERROR_TYPES:
        app.add_exception_handler(connection_error, handle_database_unavailable)
    app.add_exception_handler(DBAPIError, build_dbapi_error_handler(unexpected_error_handler))
    app.add_exception_handler(Exception, unexpected_error_handler)


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer an expected failure with the status and code the error itself carries."""
    app_error = cast(AppError, exc)
    return build_error_response(app_error.status_code, app_error.code, app_error.message)


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Answer a raised HTTPException in the envelope, never echoing the requested path.

    The exception's own headers are carried through, because Starlette's 405 sets `Allow` and a
    response that drops it tells the client nothing about which methods it could have used.
    """
    http_exception = cast(StarletteHTTPException, exc)
    code = HTTP_EXCEPTION_CODES.get(http_exception.status_code, ErrorCode.SERVER_INTERNAL_ERROR)
    return build_error_response(
        http_exception.status_code,
        code,
        HTTP_EXCEPTION_MESSAGES[code],
        headers=http_exception.headers,
    )


async def handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer 400 with the field errors summarized, so the client can name the bad input."""
    validation_error = cast(RequestValidationError, exc)
    return build_error_response(
        400, ErrorCode.INPUT_VALIDATION_ERROR, summarize_field_errors(validation_error)
    )


async def handle_database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Answer 503 when the database could not be reached, rather than a bare 500."""
    logger.warning("request_database_unavailable", error_type=type(exc).__name__)
    return build_error_response(
        503, ErrorCode.SERVER_DATABASE_UNAVAILABLE, DATABASE_UNAVAILABLE_MESSAGE
    )


def build_dbapi_error_handler(
    unexpected_error_handler: Callable[[Request, Exception], Awaitable[JSONResponse]],
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Return a handler answering 503 only for a DBAPIError that is a lost connection.

    Registering `DBAPIError` wholesale would answer 503 for an integrity violation too, which is
    the client's fault rather than an outage, so anything that is not a connection failure falls
    through to the unexpected-error handler and its 500.
    """

    async def handle_dbapi_error(request: Request, exc: Exception) -> JSONResponse:
        if is_lost_connection(cast(DBAPIError, exc)):
            return await handle_database_unavailable(request, exc)
        return await unexpected_error_handler(request, exc)

    return handle_dbapi_error


def is_lost_connection(exc: DBAPIError) -> bool:
    """Return True when the wrapped driver error says the connection itself failed."""
    if getattr(exc, "connection_invalidated", False):
        return True
    cause: BaseException | None = exc.orig
    while cause is not None:
        if isinstance(cause, ASYNCPG_CONNECTION_ERRORS):
            return True
        cause = cause.__cause__ or (cause.args[0] if _wraps_an_exception(cause) else None)
    return False


def _wraps_an_exception(cause: BaseException) -> bool:
    """Return True when the driver adapter carried the real error as its single argument."""
    return bool(cause.args) and isinstance(cause.args[0], BaseException)


def build_unexpected_error_handler(
    settings: Settings,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Return the 500 handler, which reveals the exception's message outside production only."""

    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Starlette moves a handler keyed on Exception into ServerErrorMiddleware, the outermost
        # layer, so this response never passes back through the correlation middleware and the
        # request-ID log binding has already been unwound. The contextvar is still set, so the ID
        # is read here and put on both the log line and the response, which is what keeps B-2
        # true for a 500 as well as for every other status.
        request_id = correlation_id.get()
        logger.error("request_unhandled_exception", exc_info=exc, request_id=request_id)
        message = (
            INTERNAL_ERROR_MESSAGE
            if settings.environment == "production"
            else f"{INTERNAL_ERROR_MESSAGE}: {exc}"
        )
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        return build_error_response(500, ErrorCode.SERVER_INTERNAL_ERROR, message, headers=headers)

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
