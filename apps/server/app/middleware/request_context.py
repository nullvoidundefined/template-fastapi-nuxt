"""Binds the request ID to every log line for one request and caps the request body at 100 KB.

asgi-correlation-id, which wraps this middleware, validates or mints the ID and echoes it on the
response. This class binds that ID into structlog's per-request context, clears it when the
request ends so it never leaks into later log lines, and rejects a body over 100 KB with 413,
whether the body declares its length or streams without one.
"""

import structlog
from asgi_correlation_id import correlation_id
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 100 * 1024


class BodyTooLargeError(Exception):
    """Raised from the wrapped receive when a streamed body passes the size limit."""


class RequestContextMiddleware:
    """Pure ASGI middleware: request-ID log context plus the request body size limit."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind the ID, enforce the body limit, and always clear the log context afterwards."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        structlog.contextvars.bind_contextvars(request_id=correlation_id.get())
        try:
            await self._handle_http(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject a declared oversized body at once, otherwise count the streamed bytes."""
        if _declared_length(scope) > MAX_BODY_BYTES:
            await _send_payload_too_large(scope, receive, send)
            return
        response_started = False

        async def track_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, _limited_receive(receive), track_start)
        except BodyTooLargeError:
            if response_started:
                raise
            await _send_payload_too_large(scope, receive, send)


def _declared_length(scope: Scope) -> int:
    """Return the Content-Length header as an integer, or 0 when absent or malformed."""
    for name, value in scope["headers"]:
        if name == b"content-length":
            return int(value) if value.isdigit() else 0
    return 0


def _limited_receive(receive: Receive) -> Receive:
    """Wrap receive so a streamed body raises BodyTooLargeError once it passes the limit."""
    received_bytes = 0

    async def receive_within_limit() -> Message:
        nonlocal received_bytes
        message = await receive()
        if message["type"] == "http.request":
            received_bytes += len(message.get("body", b""))
            if received_bytes > MAX_BODY_BYTES:
                raise BodyTooLargeError
        return message

    return receive_within_limit


async def _send_payload_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    """Answer 413; slice 02 moves this onto the { code, error } envelope."""
    response = JSONResponse({"error": "Request body too large"}, status_code=413)
    await response(scope, receive, send)
