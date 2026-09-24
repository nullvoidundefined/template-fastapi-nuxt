"""Builds the FastAPI application; uvicorn runs `app.main:create_app` as a factory."""

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
from starlette.middleware.cors import CORSMiddleware

from app.clients.job_queue import create_job_queue
from app.clients.analytics import create_analytics_client
from app.clients.r2 import create_r2_client
from app.clients.sentry import initialize_sentry
from app.constants.error_codes import ErrorCode
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.engine import create_database_engine
from app.errors import DATABASE_UNAVAILABLE_MESSAGE, AppError, build_error_response
from app.middleware.csrf_guard import CSRF_HEADER_MISSING_MESSAGE, CsrfGuardMiddleware
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware, is_valid_request_id
from app.middleware.request_timeout import RequestTimeoutMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware, build_security_headers
from app.routers import admin, auth, health, uploads
from app.schemas.errors import ErrorResponse, FieldError

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_TIMEOUT_SECONDS = 30
ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# `X-Requested-With` is listed because the CSRF guard requires it: a browser may only send it
# cross-origin once the preflight allows it, which is what ties the two protections together.
ALLOWED_CORS_HEADERS = ["Content-Type", "X-Requested-With", "Idempotency-Key", "X-Request-Id"]
# A browser can read only the headers a response exposes. Sending `Retry-After` on a 429 that the
# cross-origin caller cannot read makes the limit unactionable for exactly the clients the
# `CORS_ORIGIN` path exists for, and the request ID is what a user reports a failure by.
EXPOSED_CORS_HEADERS = ["Retry-After", "X-Request-Id"]

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
    ErrorCode.CSRF_HEADER_MISSING: CSRF_HEADER_MISSING_MESSAGE,
    ErrorCode.ROUTING_NOT_FOUND: "The requested resource was not found",
    ErrorCode.ROUTING_METHOD_NOT_ALLOWED: "That method is not allowed on this resource",
    ErrorCode.SERVER_INTERNAL_ERROR: "The request could not be completed",
}
# A lost connection reaches the handler as one of these. `OperationalError` is what the track
# names, and the asyncpg dialect wraps a mid-request disconnect as a plain `DBAPIError`, so both
# shapes are registered. The builtin socket errors are deliberately not: `ConnectionError` and
# `socket.gaierror` cover every peer failure a route can raise, database or not, and while they
# were registered here a failing outbound HTTP or Redis call answered `SERVER_DATABASE_UNAVAILABLE`
# and pointed the operator at the wrong dependency (IAN-169). A refused connect is now classified
# by `app.db.session.get_connection`, the one place a request opens a connection at all.
CONNECTION_ERROR_TYPES = (OperationalError,)
ASYNCPG_CONNECTION_ERRORS = (
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.InterfaceError,
)
INTERNAL_ERROR_MESSAGE = "Internal server error"
VALIDATION_ERROR_MESSAGE = "The request body failed validation"


def create_app() -> FastAPI:
    """Assemble settings, logging, error reporting, the lifespan, clients, middleware, routers."""
    settings = get_settings()
    configure_logging(settings)
    initialize_sentry(settings)
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
    register_integrations(app, settings)
    register_middleware(app, settings)
    register_exception_handlers(app, settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(uploads.router)
    return app


def register_integrations(app: FastAPI, settings: Settings) -> None:
    """Build the provider clients once per application; each is a no-op when unconfigured."""
    app.state.analytics_client = create_analytics_client(settings)
    app.state.storage_client = create_r2_client(settings)


def build_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Return a lifespan that opens the engine and the job queue, and closes both on shutdown."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_database_engine(settings)
        app.state.job_queue = create_job_queue(settings)
        try:
            yield
        finally:
            # Nested, so a Redis error while closing the queue cannot skip the engine's disposal.
            try:
                await app.state.job_queue.aclose()
            finally:
                await app.state.engine.dispose()

    return lifespan


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Add middleware innermost first, so the request passes the chain in the documented order.

    Starlette wraps middleware outside in, so the layer added last runs first. These calls are
    therefore written in reverse of the runtime order, which reads outermost inward as: the
    correlation ID (1a), the request context (1b), the security headers (2), CORS (3), the rate
    limiter (4), the timeout (5), the CSRF guard (6), and the idempotency middleware innermost
    (7), so a guard's refusal never claims a key and the stored response is the route's own.
    Writing the calls in runtime order would invert the chain and put the request-ID binding
    inside the guards, so a rejection would log without it.

    The correlation ID is outermost so every response carries a request ID, a guard's rejection
    included. The request context stays immediately inside it because that is where the structlog
    binding happens and where the body limit runs, both of which must precede the guards. The
    security headers sit above CORS so they decorate rejections as well as successes, and CORS
    precedes the guards so a preflight is answered rather than refused by a guard it cannot
    satisfy. `tests/unit/test_main_middleware_order.py` is what holds this order in place.
    """
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CsrfGuardMiddleware)
    app.add_middleware(RequestTimeoutMiddleware, seconds=REQUEST_TIMEOUT_SECONDS)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        # An empty list, not a wildcard, when no origin is configured: outside production the
        # frontend is same-origin through the Nitro proxy, so nothing needs CORS at all, and a
        # wildcard default would be the one that survived into a deployment by accident.
        allow_origins=[settings.cors_origin] if settings.cors_origin else [],
        allow_credentials=True,
        allow_methods=ALLOWED_CORS_METHODS,
        allow_headers=ALLOWED_CORS_HEADERS,
        expose_headers=EXPOSED_CORS_HEADERS,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=REQUEST_ID_HEADER,
        validator=is_valid_request_id,
    )
    # Outermost of all, rather than the position 2 the plan first named. The body limit in
    # RequestContextMiddleware answers its own 413 without calling anything below it, so a
    # security-headers layer registered inside it never sees that response. B-35 says every
    # response, and a rejection an attacker can provoke at will is the last one to leave
    # undefended. The headers need nothing the layers below them set, so nothing is lost by
    # hoisting them; the 500 that Starlette's own ServerErrorMiddleware writes sits outside every
    # user layer and is decorated by the handler itself instead.
    app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)


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
        400,
        ErrorCode.INPUT_VALIDATION_ERROR,
        summarize_field_errors(validation_error),
        field_errors=collect_field_errors(validation_error),
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
        # The same reason the request ID is set by hand here applies to the security headers:
        # this response never passes back out through the middleware that would have added them.
        headers = {
            name.decode(): value.decode()
            for name, value in build_security_headers(settings.environment)
        }
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        return build_error_response(500, ErrorCode.SERVER_INTERNAL_ERROR, message, headers=headers)

    return handle_unexpected_error


def collect_field_errors(validation_error: RequestValidationError) -> list[FieldError]:
    """Return one entry per rejected field, so a form can show each message beside its input."""
    return [
        FieldError(field=format_error_location(error["loc"]), message=error["msg"])
        for error in validation_error.errors()
    ]


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
