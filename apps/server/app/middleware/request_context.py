"""Binds the request ID to every log line for one request and caps the request body at 100 KB.

asgi-correlation-id, which wraps this middleware, validates or mints the ID and echoes it on the
response; the validator it uses lives here with the rest of the request-ID concern. This class
binds that ID into structlog's per-request context and restores whatever was bound before when
the request ends, and it rejects a body over 100 KB with 413 whether the body declares its
length or streams without one.

A streamed body that passes the limit is answered with 413 immediately, and the app then sees a
disconnect, so whatever it tries to send afterwards (FastAPI turns an interrupted body read into
a 400) is dropped. Raising an exception from receive would not work: FastAPI catches any
exception raised while it reads a Pydantic body and converts it into that 400.
"""

import json
import re

import structlog
from asgi_correlation_id import correlation_id
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 100 * 1024
MAX_CONTENT_LENGTH_DIGITS = 19
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
PAYLOAD_TOO_LARGE_CODE = "INPUT_PAYLOAD_TOO_LARGE"
PAYLOAD_TOO_LARGE_MESSAGE = "Request body exceeds 100 KB"


def is_valid_request_id(candidate: str) -> bool:
    """Accept an inbound request ID only when it is 1 to 64 safe characters."""
    return REQUEST_ID_PATTERN.fullmatch(candidate) is not None


class RequestContextMiddleware:
    """Pure ASGI middleware: request-ID log context plus the request body size limit."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind the ID for the length of the request, then restore the previous context."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with structlog.contextvars.bound_contextvars(request_id=correlation_id.get()):
            await self._handle_http(scope, receive, send)

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject a declared oversized body at once, otherwise enforce it while the body streams.

        Once the guard has answered 413, the app's own reaction to the disconnect (a body-read
        error, a 400) is expected and already superseded, so it is dropped rather than raised.
        """
        if _declares_oversized_body(scope):
            await _send_payload_too_large(send)
            return
        guard = _StreamedBodyGuard(scope, receive, send)
        try:
            await self.app(scope, guard.receive, guard.send)
        except Exception:
            if not guard.is_rejected:
                raise


class _StreamedBodyGuard:
    """Counts streamed body bytes and answers 413 the moment they pass the limit."""

    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Hold the real channel and start with nothing received and nothing sent."""
        self._scope = scope
        self._receive = receive
        self._send = send
        self._received_bytes = 0
        self._response_started = False
        self._rejected = False

    @property
    def is_rejected(self) -> bool:
        """Return True once the guard has answered 413 in place of the app."""
        return self._rejected

    async def receive(self) -> Message:
        """Pass body messages through until the limit, then answer 413 and report a disconnect."""
        if self._rejected:
            return {"type": "http.disconnect"}
        message = await self._receive()
        if message["type"] == "http.request":
            self._received_bytes += len(message.get("body", b""))
            if self._received_bytes > MAX_BODY_BYTES and not self._response_started:
                self._rejected = True
                await _send_payload_too_large(self._send)
                return {"type": "http.disconnect"}
        return message

    async def send(self, message: Message) -> None:
        """Forward the app's response unless a 413 has already been sent in its place."""
        if self._rejected:
            return
        if message["type"] == "http.response.start":
            self._response_started = True
        await self._send(message)


def _declares_oversized_body(scope: Scope) -> bool:
    """Return True when the Content-Length header names more than the limit."""
    for name, value in scope["headers"]:
        if name == b"content-length":
            if not value.isdigit():
                return False
            return len(value) > MAX_CONTENT_LENGTH_DIGITS or int(value) > MAX_BODY_BYTES
    return False


async def _send_payload_too_large(send: Send) -> None:
    """Answer 413 in the { code, error } envelope as raw ASGI messages.

    Sending the messages directly, rather than through a Starlette response, never reads from
    the request's receive channel, which a streamed body may already have consumed.
    """
    body = json.dumps({"code": PAYLOAD_TOO_LARGE_CODE, "error": PAYLOAD_TOO_LARGE_MESSAGE}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
