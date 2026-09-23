"""The exception types routes and services raise, and the one builder that answers them.

An `AppError` carries its own status and registry code, so a route says what went wrong and the
handler in `main.py` turns it into the envelope without a mapping table in between. Everything
that is not an `AppError` is unexpected by definition and reaches the 500 handler.
"""

import json
from collections.abc import Mapping

from fastapi.responses import JSONResponse
from starlette.types import Send

from app.constants.error_codes import ErrorCode
from app.schemas.errors import ErrorResponse, FieldError

DATABASE_UNAVAILABLE_MESSAGE = "The database is unavailable"


class AppError(Exception):
    """An expected failure with the status and registry code the response should carry."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        """Record the response status, the registry code, and the message to return."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class NotFoundError(AppError):
    """The requested resource does not exist, or does not belong to this user."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        """Answer 404 with the given registry code."""
        super().__init__(status_code=404, code=code, message=message)


class ConflictError(AppError):
    """The request cannot be applied to the current state of the resource."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        """Answer 409 with the given registry code."""
        super().__init__(status_code=409, code=code, message=message)


class ForbiddenError(AppError):
    """The caller is known but not permitted to do this."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        """Answer 403 with the given registry code."""
        super().__init__(status_code=403, code=code, message=message)


class DatabaseUnavailableError(AppError):
    """Postgres could not be reached, so the request cannot be served at all.

    Raised by `app.db.session.get_connection`, the one place a request opens a connection. It is
    an `AppError` rather than a case in a global handler so that only a real connect failure is
    ever reported to a client as a database outage.
    """

    def __init__(self, message: str = DATABASE_UNAVAILABLE_MESSAGE) -> None:
        """Answer 503 with the registry's database-unavailable code."""
        super().__init__(
            status_code=503, code=ErrorCode.SERVER_DATABASE_UNAVAILABLE, message=message
        )


def build_error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    headers: Mapping[str, str] | None = None,
    field_errors: list[FieldError] | None = None,
) -> JSONResponse:
    """Return the `{ code, error }` envelope as a JSON response with the given status.

    `field_errors` is excluded when absent rather than serialized as null, so a failure that is
    not a validation error answers the same two keys it always has.
    """
    envelope = ErrorResponse(code=code, error=message, field_errors=field_errors)
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


async def send_error_envelope(
    send: Send,
    status_code: int,
    code: ErrorCode,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> None:
    """Send the `{ code, error }` envelope as raw ASGI messages, for middleware that cannot raise.

    Pure ASGI middleware sits outside Starlette's `ExceptionMiddleware`, so an `AppError` raised
    there never reaches `register_exception_handlers` and would reach the client as a bare 500.
    Writing the response here keeps the envelope identical to the one the handlers produce.

    Sending the messages directly, rather than through a Starlette response, also never reads from
    the request's receive channel, which a streamed body may already have consumed.

    `headers` carries the few a rejection must add, such as the rate limiter's `Retry-After`.
    """
    body = json.dumps(
        ErrorResponse(code=code, error=message).model_dump(mode="json", exclude_none=True)
    ).encode()
    extra_headers = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *extra_headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
