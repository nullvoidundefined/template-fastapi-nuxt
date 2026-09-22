"""The exception types routes and services raise, and the one builder that answers them.

An `AppError` carries its own status and registry code, so a route says what went wrong and the
handler in `main.py` turns it into the envelope without a mapping table in between. Everything
that is not an `AppError` is unexpected by definition and reaches the 500 handler.
"""

from collections.abc import Mapping

from fastapi.responses import JSONResponse

from app.constants.error_codes import ErrorCode
from app.schemas.errors import ErrorResponse

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
) -> JSONResponse:
    """Return the `{ code, error }` envelope as a JSON response with the given status."""
    envelope = ErrorResponse(code=code, error=message)
    return JSONResponse(
        status_code=status_code, content=envelope.model_dump(mode="json"), headers=headers
    )
