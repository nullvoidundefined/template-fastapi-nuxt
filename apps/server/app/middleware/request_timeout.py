"""Cancels a handler that runs past its deadline and answers 408 (spec B-8).

The point of the timeout is to stop the work, not only to stop waiting for it. `asyncio.timeout`
cancels the task running the downstream app, so a handler holding a database connection or an
upstream request releases it instead of running on unobserved behind a response the client already
has. The test asserts the cancellation as well as the status, so an implementation that answered
408 and left the handler running would fail.

The deadline is a constructor argument rather than a module constant, so a test can inject a short
one instead of waiting the production 30 seconds.

The response is written as raw ASGI messages through `send_error_envelope`, for the same reason as
the CSRF guard: this is pure ASGI middleware, outside Starlette's `ExceptionMiddleware`.
"""

import asyncio

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.constants.error_codes import ErrorCode
from app.errors import send_error_envelope

REQUEST_TIMEOUT_MESSAGE = "Request timed out"

logger = structlog.get_logger(__name__)


class RequestTimeoutMiddleware:
    """Pure ASGI middleware bounding how long the downstream app may take to answer."""

    def __init__(self, app: ASGIApp, seconds: float) -> None:
        """Wrap the downstream app and fix the deadline it must answer within."""
        self.app = app
        self.seconds = seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the app under the deadline; answer 408 when it expires before the response starts."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def track_response_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            async with asyncio.timeout(self.seconds):
                await self.app(scope, receive, track_response_start)
        except TimeoutError:
            logger.warning("request_timed_out", path=scope["path"], timeout_seconds=self.seconds)
            # A handler that already began streaming has sent its status line, so the envelope
            # cannot replace it; the connection simply ends, and the log line is the record.
            if not response_started:
                await send_error_envelope(
                    send, 408, ErrorCode.SERVER_REQUEST_TIMEOUT, REQUEST_TIMEOUT_MESSAGE
                )
