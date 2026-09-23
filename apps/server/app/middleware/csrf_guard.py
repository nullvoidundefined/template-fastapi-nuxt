"""Rejects a state-changing request that does not carry the `X-Requested-With` header (spec B-6).

Cookie sessions are sent by the browser on a cross-site form post, so the cookie alone cannot say
whether the user meant to make the request. A custom header can: a browser will not attach one
cross-origin without a CORS preflight, and CORS is configured to allow only `CORS_ORIGIN`, so a
foreign origin never gets the preflight that would let it send the header. That is why this guard
and the CORS configuration are one protection rather than two, and why neither is optional.

Safe methods are never checked, because they change nothing. The exemptions in
`app.constants.exempt_paths` are compared by equality rather than by prefix.

The rejection is written as raw ASGI messages through `send_error_envelope`. This is pure ASGI
middleware, outside Starlette's `ExceptionMiddleware`, so raising an `AppError` here would never
reach `register_exception_handlers` and the client would get a bare 500 instead of the envelope.
"""

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.constants.error_codes import ErrorCode
from app.constants.exempt_paths import CSRF_EXEMPT_PATHS
from app.errors import send_error_envelope

CSRF_HEADER_NAME = b"x-requested-with"
CSRF_HEADER_VALUE = b"XMLHttpRequest"
CSRF_HEADER_MISSING_MESSAGE = "That request is not allowed"
# GET, HEAD, and OPTIONS change nothing, and TRACE is not served; everything else is guarded, so a
# method added later is guarded by default rather than by being remembered here.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

logger = structlog.get_logger(__name__)


class CsrfGuardMiddleware:
    """Pure ASGI middleware answering 403 when an unsafe request lacks the CSRF header."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request through unless it is unsafe, not exempt, and missing the header."""
        if scope["type"] != "http" or is_request_allowed(scope):
            await self.app(scope, receive, send)
            return
        # The client is told nothing beyond the code, so the log line is the only record of why a
        # request was refused. It carries the request ID through the context bound one layer out.
        logger.warning("csrf_header_missing", method=scope["method"], path=scope["path"])
        await send_error_envelope(
            send, 403, ErrorCode.CSRF_HEADER_MISSING, CSRF_HEADER_MISSING_MESSAGE
        )


def is_request_allowed(scope: Scope) -> bool:
    """Return True when this request needs no CSRF header, or already carries it."""
    if scope["method"] in SAFE_METHODS:
        return True
    if scope["path"] in CSRF_EXEMPT_PATHS:
        return True
    return has_csrf_header(scope)


def has_csrf_header(scope: Scope) -> bool:
    """Return True when the request carries `X-Requested-With: XMLHttpRequest`."""
    return any(
        name == CSRF_HEADER_NAME and value == CSRF_HEADER_VALUE for name, value in scope["headers"]
    )
