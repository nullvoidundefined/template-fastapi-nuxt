"""Makes an authenticated `POST` or `PUT` carrying `Idempotency-Key` safe to retry (spec B-17).

Layer 7, the innermost middleware: it runs after every guard, so a refused request never claims a
key, and it sees the final response the route produced, which is what it stores. It resolves the
session cookie itself, through the same repository function as the session dependency, because a
dependency runs inside the route and this has to decide before the route runs. A request with no
key, no live session, or another method passes straight through.

The protocol, each step in its own short transaction on a connection of its own, so other
requests see a claim the moment it is taken and every lease is judged by the database's `now()`:

1. Claim the key with one `INSERT ... ON CONFLICT`. Taken: run the handler.
2. Otherwise read the row. A different method, path, or body answers 422
   `IDEMPOTENCY_KEY_REUSED` and runs nothing (B-40). A completed row replays its stored status and
   body without running the handler. An in-progress row inside its lease answers 409
   `IDEMPOTENCY_KEY_IN_PROGRESS` (B-44).
3. An in-progress row past its lease was left by a holder that died, and is taken over with one
   conditional `UPDATE`, so only one of several takeovers wins. A takeover that wins nothing
   re-reads the row and answers as in step 2. A row that has vanished was released by its holder
   between the read and the takeover, and the claim insert is retried once (B-53).

After the handler: a 2xx to 4xx response is stored and the claim completed; an exception or a 5xx
releases the claim, so the client's retry runs again (B-18). Both statements carry this request's
claim token, so a holder that was taken over changes nothing.

What is stored is the raw body bytes, the content type, and the allowlisted headers, so a
plain-text or binary response replays exactly as a JSON one does (IAN-339). The capture is
bounded: a response that streams, sending its body in several messages without declaring a
Content-Length, or one past `MAX_STORED_RESPONSE_BYTES`, stops being buffered the moment it is
recognized, still reaches the client whole, and releases its claim rather than being stored. That
trades the retry's protection for bounded memory, and no route streams or answers that much today.
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.constants.error_codes import ErrorCode
from app.constants.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_KEY_PATTERN,
    IDEMPOTENT_METHODS,
    MAX_STORED_RESPONSE_BYTES,
    REPLAYED_RESPONSE_HEADERS,
    IdempotencyKeyState,
)
from app.constants.session import SESSION_COOKIE_NAME
from app.core.security import hash_token
from app.db.session import CONNECT_FAILURE_TYPES
from app.errors import DATABASE_UNAVAILABLE_MESSAGE, send_error_envelope
from app.repositories.request_idempotency_keys import (
    IdempotentRequest,
    StoredResponse,
    claim_idempotency_key,
    complete_idempotency_key,
    read_idempotency_key,
    release_idempotency_key,
    take_over_idempotency_key,
)
from app.repositories.user_sessions import find_session_with_user

INVALID_KEY_MESSAGE = "Idempotency-Key must be 1 to 255 printable ASCII characters"
KEY_REUSED_MESSAGE = "That Idempotency-Key was already used for a different request"
KEY_IN_PROGRESS_MESSAGE = "A request with that Idempotency-Key is still in progress"
CLAIM_INSERT_ATTEMPTS = 2
SERVER_ERROR_STATUS = 500
JSON_CONTENT_TYPE = "application/json"
JSON_MEDIA_TYPE_SUFFIX = "+json"
# RFC 9110 forbids a Content-Length on these, so a replay of one sends none, as the handler did.
BODILESS_STATUSES = frozenset({204, 304})

# Storing the response is retried this many times, with a short growing pause, before the
# claim is left for its lease to lapse.
COMPLETION_ATTEMPTS = 3
COMPLETION_RETRY_DELAY_SECONDS = 0.05
# Settlements still running after their request task was cancelled, held so none is collected.
PENDING_SETTLEMENTS: set["asyncio.Future[None]"] = set()

logger = structlog.get_logger(__name__)


class ClaimDecision(Enum):
    """What a read of an existing claim tells this request to do."""

    CLAIMED = "claimed"
    REPLAY = "replay"
    REUSED = "reused"
    IN_PROGRESS = "in_progress"
    TAKE_OVER = "take_over"
    GONE = "gone"


@dataclass(slots=True, frozen=True)
class ClaimOutcome:
    """The decision, and for a replay the stored row to answer with."""

    decision: ClaimDecision
    stored: Row[Any] | None = None


@dataclass(slots=True, frozen=True)
class RequestClaim:
    """One authenticated request's claim: its identity, its token, and what to do with it."""

    engine: AsyncEngine
    request: IdempotentRequest
    claim_token: uuid.UUID
    outcome: ClaimOutcome


class UnstoredReason(Enum):
    """Why a response passed through without being stored for replay."""

    STREAMING = "streaming"
    TOO_LARGE = "too_large"


@dataclass(slots=True)
class CapturedResponse:
    """What the handler sent, recorded as it passes through to the client, up to the cap.

    Once `unstored_reason` is set the body chunks are dropped and nothing more is buffered.
    """

    status: int | None = None
    content_type: str | None = None
    headers: list[tuple[str, str]] = field(default_factory=list)
    has_content_length: bool = False
    body_chunks: list[bytes] = field(default_factory=list)
    body_size: int = 0
    unstored_reason: UnstoredReason | None = None


class IdempotencyMiddleware:
    """Pure ASGI middleware claiming, replaying, and releasing idempotency keys."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass through unless this is a keyed POST or PUT; otherwise run the claim protocol."""
        raw_key = read_idempotency_key_header(scope)
        if raw_key is None:
            await self.app(scope, receive, send)
            return
        key = raw_key.decode("latin-1")
        if IDEMPOTENCY_KEY_PATTERN.fullmatch(key) is None:
            await send_error_envelope(
                send, 400, ErrorCode.INPUT_VALIDATION_ERROR, INVALID_KEY_MESSAGE
            )
            return
        body_messages, body = await read_request_body(receive)
        replayed_receive = build_replay_receive(body_messages, receive)

        try:
            claim = await resolve_request_claim(scope, key, body)
        except CONNECT_FAILURE_TYPES as err:
            # This layer is outside the exception handlers, so it answers the envelope itself.
            logger.warning("idempotency_database_unavailable", error_type=type(err).__name__)
            await send_error_envelope(
                send, 503, ErrorCode.SERVER_DATABASE_UNAVAILABLE, DATABASE_UNAVAILABLE_MESSAGE
            )
            return
        if claim is None:
            # Anonymous: the route decides whether it needs a user, and nothing is claimed.
            await self.app(scope, replayed_receive, send)
            return
        await self.answer_claim(scope, replayed_receive, send, claim)

    async def answer_claim(
        self, scope: Scope, receive: Receive, send: Send, claim: RequestClaim
    ) -> None:
        """Run the handler for a claim, replay a completed one, or refuse with 409 or 422."""
        decision = claim.outcome.decision
        if decision is ClaimDecision.CLAIMED:
            await self.run_claimed_request(scope, receive, send, claim)
        elif decision is ClaimDecision.REPLAY and claim.outcome.stored is not None:
            logger.info("idempotency_replayed", path=claim.request.path)
            await send_stored_response(send, claim.outcome.stored)
        elif decision is ClaimDecision.REUSED:
            logger.warning("idempotency_key_reused", path=claim.request.path)
            await send_error_envelope(
                send, 422, ErrorCode.IDEMPOTENCY_KEY_REUSED, KEY_REUSED_MESSAGE
            )
        else:
            await send_error_envelope(
                send, 409, ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS, KEY_IN_PROGRESS_MESSAGE
            )

    async def run_claimed_request(
        self, scope: Scope, receive: Receive, send: Send, claim: RequestClaim
    ) -> None:
        """Run the handler under the claim, then complete or release it by its outcome."""
        captured = CapturedResponse()

        async def capture_and_send(message: Message) -> None:
            record_response_message(captured, message)
            await send(message)

        try:
            await self.app(scope, receive, capture_and_send)
        except BaseException:
            # BaseException, because a request timeout cancels this task, and a cancelled handler
            # must release its claim exactly as a failing one does.
            await release_claim_safely(claim)
            raise
        # Shielded: the handler has answered and its transaction has committed, so a timeout that
        # lands now must not strand the claim in progress, where a retry would take it over and
        # run the side effect again. The settlement finishes even when this task is cancelled.
        settlement = asyncio.ensure_future(settle_claim(claim, captured))
        # Held until done: once this task is cancelled nothing else references the settlement,
        # and the event loop keeps only a weak reference to a running task.
        PENDING_SETTLEMENTS.add(settlement)
        settlement.add_done_callback(PENDING_SETTLEMENTS.discard)
        await asyncio.shield(settlement)


async def resolve_request_claim(scope: Scope, key: str, body: bytes) -> "RequestClaim | None":
    """Resolve the session's user and then the claim; None for an anonymous request."""
    engine: AsyncEngine = scope["app"].state.engine
    user_id = await resolve_session_user_id(engine, scope)
    if user_id is None:
        return None
    request = IdempotentRequest(
        key=key,
        user_id=user_id,
        method=scope["method"],
        path=read_request_target(scope),
        body_hash=hashlib.sha256(body).hexdigest(),
    )
    claim_token = uuid.uuid4()
    outcome = await resolve_claim(engine, request, claim_token)
    return RequestClaim(engine, request, claim_token, outcome)


def read_request_target(scope: Scope) -> str:
    """Return the path with its query string, since both are part of what a key promises.

    The bytes are compared as sent, unsorted: a genuine retry resends the identical request, so a
    reordered query string under the same key is treated as a different request, which is safe.
    """
    query_string = scope.get("query_string", b"").decode("latin-1")
    return f"{scope['path']}?{query_string}" if query_string else scope["path"]


def read_idempotency_key_header(scope: Scope) -> bytes | None:
    """Return the raw key of a POST or PUT over HTTP, or None when idempotency does not apply."""
    if scope["type"] != "http" or scope["method"] not in IDEMPOTENT_METHODS:
        return None
    for name, value in scope["headers"]:
        if name == IDEMPOTENCY_KEY_HEADER:
            return bytes(value)
    return None


async def read_request_body(receive: Receive) -> tuple[list[Message], bytes]:
    """Read the whole body, which the request-context layer has already bounded at 100 KB."""
    messages: list[Message] = []
    chunks: list[bytes] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return messages, b"".join(chunks)


def build_replay_receive(messages: list[Message], receive: Receive) -> Receive:
    """Hand the buffered body to the app, then fall through to the real channel."""
    pending = list(messages)

    async def replay() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return replay


async def resolve_session_user_id(engine: AsyncEngine, scope: Scope) -> uuid.UUID | None:
    """Return the id of the user whose live session the cookie names, or None."""
    raw_token = Request(scope).cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None
    async with engine.connect() as connection:
        session_row = await find_session_with_user(connection, hash_token(raw_token))
    if session_row is None or session_row.expires_at <= datetime.now(UTC):
        return None
    return uuid.UUID(str(session_row.user_id))


async def resolve_claim(
    engine: AsyncEngine, request: IdempotentRequest, claim_token: uuid.UUID
) -> ClaimOutcome:
    """Claim the key, or decide from the existing row; a vanished row retries the insert once."""
    for _attempt in range(CLAIM_INSERT_ATTEMPTS):
        async with engine.begin() as connection:
            if await claim_idempotency_key(connection, request, claim_token):
                return ClaimOutcome(ClaimDecision.CLAIMED)
        outcome = await judge_stored_claim(engine, request)
        if outcome.decision is ClaimDecision.TAKE_OVER:
            outcome = await attempt_take_over(engine, request, claim_token)
        if outcome.decision is not ClaimDecision.GONE:
            return outcome
    return ClaimOutcome(ClaimDecision.IN_PROGRESS)


async def attempt_take_over(
    engine: AsyncEngine, request: IdempotentRequest, claim_token: uuid.UUID
) -> ClaimOutcome:
    """Take the expired claim over, or re-read it when another request moved first."""
    async with engine.begin() as connection:
        if await take_over_idempotency_key(connection, request, claim_token):
            logger.info("idempotency_claim_taken_over", path=request.path)
            return ClaimOutcome(ClaimDecision.CLAIMED)
    outcome = await judge_stored_claim(engine, request)
    if outcome.decision is ClaimDecision.TAKE_OVER:
        # Expired again between two statements: another request is contending for it, and
        # waiting for the client's retry is safer than a loop.
        return ClaimOutcome(ClaimDecision.IN_PROGRESS)
    return outcome


async def judge_stored_claim(engine: AsyncEngine, request: IdempotentRequest) -> ClaimOutcome:
    """Read the claim on its own connection and decide what this request should do with it."""
    async with engine.connect() as connection:
        stored = await read_idempotency_key(connection, request.key, request.user_id)
    return decide_from_stored_claim(stored, request)


def decide_from_stored_claim(stored: Row[Any] | None, request: IdempotentRequest) -> ClaimOutcome:
    """Map a stored claim to reuse, replay, a live lease, an expired one, or nothing at all."""
    if stored is None or not stored.is_within_replay_window:
        return ClaimOutcome(ClaimDecision.GONE)
    if not is_same_request(stored, request):
        return ClaimOutcome(ClaimDecision.REUSED)
    if stored.state == IdempotencyKeyState.COMPLETED.value:
        return ClaimOutcome(ClaimDecision.REPLAY, stored)
    if stored.is_lease_live:
        return ClaimOutcome(ClaimDecision.IN_PROGRESS)
    return ClaimOutcome(ClaimDecision.TAKE_OVER)


def is_same_request(stored: Row[Any], request: IdempotentRequest) -> bool:
    """Return True when the stored claim was taken by this same method, path, and body."""
    stored_identity = (stored.request_method, stored.request_path, stored.request_body_hash)
    return bool(stored_identity == (request.method, request.path, request.body_hash))


def record_response_message(captured: CapturedResponse, message: Message) -> None:
    """Keep the status, the storable headers, and the body chunks, until the cap is passed."""
    if message["type"] == "http.response.start":
        record_response_start(captured, message)
    elif message["type"] == "http.response.body" and captured.unstored_reason is None:
        record_response_body(captured, message)


def record_response_start(captured: CapturedResponse, message: Message) -> None:
    """Keep the status, the content type, and the allowlisted headers; judge the declared size."""
    captured.status = message["status"]
    for raw_name, raw_value in message.get("headers", []):
        name = bytes(raw_name).lower()
        value = bytes(raw_value).decode("latin-1")
        if name == b"content-type":
            captured.content_type = value
        elif name == b"content-length":
            record_declared_length(captured, value)
        elif name in REPLAYED_RESPONSE_HEADERS:
            captured.headers.append((name.decode("latin-1"), value))


def record_declared_length(captured: CapturedResponse, value: str) -> None:
    """Judge a declared Content-Length; an unparseable one counts as undeclared.

    An unparseable length must not raise here, because this runs inside the send that carries the
    handler's committed answer to the client. Treated as undeclared, the body's running total
    still bounds what is buffered.
    """
    if not value.strip().isdigit():
        return
    captured.has_content_length = True
    if int(value) > MAX_STORED_RESPONSE_BYTES:
        stop_capturing(captured, UnstoredReason.TOO_LARGE)


def record_response_body(captured: CapturedResponse, message: Message) -> None:
    """Buffer one body chunk, or stop buffering for a stream or a body past the cap."""
    if message.get("more_body", False) and not captured.has_content_length:
        stop_capturing(captured, UnstoredReason.STREAMING)
        return
    chunk = message.get("body", b"")
    captured.body_size += len(chunk)
    if captured.body_size > MAX_STORED_RESPONSE_BYTES:
        stop_capturing(captured, UnstoredReason.TOO_LARGE)
        return
    captured.body_chunks.append(chunk)


def stop_capturing(captured: CapturedResponse, reason: UnstoredReason) -> None:
    """Drop what was buffered and record why this response will not be stored."""
    captured.unstored_reason = reason
    captured.body_chunks.clear()


async def settle_claim(claim: RequestClaim, captured: CapturedResponse) -> None:
    """Complete the claim with a storable response, or release it so a retry runs again."""
    if captured.status is None or captured.status >= SERVER_ERROR_STATUS:
        await release_claim_safely(claim)
        return
    if captured.unstored_reason is not None:
        logger.warning(
            "idempotency_response_not_stored",
            path=claim.request.path,
            reason=captured.unstored_reason.value,
        )
        await release_claim_safely(claim)
        return
    await complete_claim_safely(claim, build_stored_response(captured, captured.status))


def build_stored_response(captured: CapturedResponse, status_code: int) -> StoredResponse:
    """Assemble what is stored, parsing a JSON body for the column older replicas read."""
    body = b"".join(captured.body_chunks)
    return StoredResponse(
        status_code=status_code,
        body=body,
        content_type=captured.content_type,
        headers=captured.headers,
        json_body=parse_json_body(body, captured.content_type),
    )


def parse_json_body(body: bytes, content_type: str | None) -> object:
    """Return a JSON body parsed, or None when it is empty, not JSON, or does not parse."""
    if not body or content_type is None or not is_json_media_type(content_type):
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def is_json_media_type(content_type: str) -> bool:
    """Return True for `application/json` and any `+json` suffixed type, parameters ignored."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == JSON_CONTENT_TYPE or media_type.endswith(JSON_MEDIA_TYPE_SUFFIX)


async def complete_claim_safely(claim: RequestClaim, response: StoredResponse) -> None:
    """Store the response, retrying a transient failure, because an open claim can run twice.

    The client already has its answer, so a failure is logged rather than raised. Retrying matters
    because the handler's side effect has committed: a claim left in progress is taken over once
    its lease lapses, and the retry that takes it over runs the side effect a second time.
    """
    for attempt in range(1, COMPLETION_ATTEMPTS + 1):
        try:
            async with claim.engine.begin() as connection:
                is_completed = await complete_idempotency_key(
                    connection, claim.request, claim.claim_token, response
                )
            break
        except CONNECT_FAILURE_TYPES as err:
            if attempt == COMPLETION_ATTEMPTS:
                logger.error("idempotency_completion_failed", exc_info=err, path=claim.request.path)
                return
            await asyncio.sleep(COMPLETION_RETRY_DELAY_SECONDS * attempt)
    if not is_completed:
        logger.warning("idempotency_claim_superseded", path=claim.request.path)


async def release_claim_safely(claim: RequestClaim) -> None:
    """Delete this request's claim; a failure only logs, and the lease lapses instead."""
    try:
        async with claim.engine.begin() as connection:
            await release_idempotency_key(connection, claim.request, claim.claim_token)
    except CONNECT_FAILURE_TYPES as err:
        logger.error("idempotency_release_failed", exc_info=err, path=claim.request.path)


async def send_stored_response(send: Send, stored: Row[Any]) -> None:
    """Answer with the stored status, body, content type, and headers, as raw ASGI messages."""
    body, content_type, stored_headers = read_replay_parts(stored)
    headers = []
    if stored.status_code not in BODILESS_STATUSES:
        headers.append((b"content-length", str(len(body)).encode()))
    if content_type is not None:
        headers.append((b"content-type", content_type.encode("latin-1")))
    headers.extend(
        (name.encode("latin-1"), value.encode("latin-1")) for name, value in stored_headers
    )
    await send({"type": "http.response.start", "status": stored.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def read_replay_parts(stored: Row[Any]) -> tuple[bytes, str | None, list[list[str]]]:
    """Return the body, content type, and headers to replay, from a raw row or a JSONB-only one.

    A row completed before revision 0008 has no raw body, so its JSONB body is serialized as it
    always was, with no headers, until the replay window has aged every such row out.
    """
    if stored.response_body_bytes is not None:
        return (
            bytes(stored.response_body_bytes),
            stored.response_content_type,
            (stored.response_headers or []),
        )
    if stored.response_body is None:
        return b"", None, []
    return json.dumps(stored.response_body).encode(), JSON_CONTENT_TYPE, []
