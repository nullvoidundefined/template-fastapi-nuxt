"""Binds the request ID to every log line for one request and caps the request body at 100 KB.

asgi-correlation-id, which wraps this middleware, validates or mints the ID and echoes it on the
response; the validator it uses lives here with the rest of the request-ID concern. This class
binds that ID into structlog's per-request context and restores whatever was bound before when
the request ends.

The body limit holds before the route runs (spec B-43): the whole body is read, up to the
limit, before the app is called, and then replayed to it. A body that declares or streams more
than 100 KB is answered with 413 and the app never runs, whether or not the route would have
read its body. Bodies stay small by design (uploads go to R2 through presigned URLs), so holding
at most 100 KB in memory per request is the cheaper side of the trade.
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
        """Answer 413 for an oversized body, otherwise run the app with the body replayed."""
        if _declares_oversized_body(scope):
            await _send_payload_too_large(send)
            return
        body_messages = await _read_body_within_limit(receive)
        if body_messages is None:
            await _send_payload_too_large(send)
            return
        await self.app(scope, _replay_receive(body_messages, receive), send)


async def _read_body_within_limit(receive: Receive) -> list[Message] | None:
    """Read every body message; return None as soon as the running total passes the limit."""
    body_messages: list[Message] = []
    received_bytes = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            body_messages.append(message)
            return body_messages
        received_bytes += len(message.get("body", b""))
        if received_bytes > MAX_BODY_BYTES:
            return None
        body_messages.append(message)
        if not message.get("more_body", False):
            return body_messages


def _replay_receive(body_messages: list[Message], receive: Receive) -> Receive:
    """Hand the buffered body messages to the app, then fall through to the real channel."""
    pending_messages = list(body_messages)

    async def replay() -> Message:
        if pending_messages:
            return pending_messages.pop(0)
        return await receive()

    return replay


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
