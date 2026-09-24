"""Data access for request_idempotency_keys: claim, read, take over, complete, release.

Every statement here decides in the database rather than in Python. A claim is one
`INSERT ... ON CONFLICT`, so two simultaneous requests cannot both insert; a takeover is one
conditional `UPDATE ... RETURNING`, so two takeovers of one expired lease cannot both win; and
every lease and window comparison uses Postgres's `now()`, so the application's clock never
enters into it. The completion and the release both carry `claim_token = :mine`, which is what
stops a holder that was taken over from overwriting or deleting the claim that superseded it.

The caller runs each function in its own short transaction, outside the request's transaction,
so other requests see a claim the moment it is taken.

`delete_stale_idempotency_keys_batch` is the hourly cleanup job's statement for this table: it
deletes at most one batch of keys older than the replay window, found through the `created_at`
index, and skips a row another transaction holds locked at that instant. A claim holds no lock
while its handler runs, so a key claimed or taken over near the end of the window can still be
deleted; its completion then finds nothing and the client's retry runs the handler again, the
same exposure the claim's own replay-window check already has. The batch is a materialized CTE,
for the reason `delete_expired_sessions_batch` gives: a LIMIT subquery may run more than once.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Row, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

from app.constants.cleanup import IDEMPOTENCY_KEY_RETENTION
from app.constants.idempotency import LEASE_SECONDS, REPLAY_WINDOW_HOURS, IdempotencyKeyState
from app.db.tables import request_idempotency_keys

LEASE = timedelta(seconds=LEASE_SECONDS)
REPLAY_WINDOW = timedelta(hours=REPLAY_WINDOW_HOURS)
keys = request_idempotency_keys


@dataclass(slots=True, frozen=True)
class IdempotentRequest:
    """The identity a claim binds a key to: its owner, method, path, and body hash."""

    key: str
    user_id: uuid.UUID
    method: str
    path: str
    body_hash: str


@dataclass(slots=True, frozen=True)
class StoredResponse:
    """The response a completed claim replays: status, raw body, content type, kept headers.

    `json_body` is the same body parsed, or None when it is not JSON. It is still written to the
    JSONB column revision 0005 created, so a replica running the previous release replays a JSON
    body correctly until the contract migration drops that column. That replica cannot replay a
    non-JSON body, which it would send empty, for the few seconds a rolling deploy overlaps.
    """

    status_code: int
    body: bytes
    content_type: str | None
    headers: list[tuple[str, str]]
    json_body: object


async def claim_idempotency_key(
    connection: AsyncConnection, request: IdempotentRequest, claim_token: uuid.UUID
) -> bool:
    """Insert a fresh in-progress claim, or reclaim one past the replay window; True if taken.

    A row still inside its twenty-four hour window is left untouched and nothing is returned, so
    the caller knows to read it. A row older than the window has expired as a key, and is
    overwritten in the same statement rather than deleted and reinserted in two.
    """
    values = {
        "key": request.key,
        "user_id": request.user_id,
        "request_method": request.method,
        "request_path": request.path,
        "request_body_hash": request.body_hash,
        "state": IdempotencyKeyState.IN_PROGRESS.value,
        "locked_until": func.now() + LEASE,
        "claim_token": claim_token,
    }
    insert_statement = insert(keys).values(**values)
    excluded = insert_statement.excluded
    statement = insert_statement.on_conflict_do_update(
        index_elements=[keys.c.key, keys.c.user_id],
        set_={
            **{name: excluded[name] for name in values if name not in ("key", "user_id")},
            "status_code": None,
            "response_body": None,
            "response_body_bytes": None,
            "response_content_type": None,
            "response_headers": None,
            "created_at": func.now(),
        },
        where=keys.c.created_at < func.now() - REPLAY_WINDOW,
    ).returning(keys.c.key)
    return (await connection.execute(statement)).first() is not None


async def read_idempotency_key(
    connection: AsyncConnection, key: str, user_id: uuid.UUID
) -> Row[Any] | None:
    """Return the claim with its lease and replay window judged by the database's clock."""
    statement = select(
        keys.c.request_method,
        keys.c.request_path,
        keys.c.request_body_hash,
        keys.c.state,
        keys.c.status_code,
        keys.c.response_body,
        keys.c.response_body_bytes,
        keys.c.response_content_type,
        keys.c.response_headers,
        (keys.c.locked_until > func.now()).label("is_lease_live"),
        (keys.c.created_at > func.now() - REPLAY_WINDOW).label("is_within_replay_window"),
    ).where(keys.c.key == key, keys.c.user_id == user_id)
    return (await connection.execute(statement)).one_or_none()


async def take_over_idempotency_key(
    connection: AsyncConnection, request: IdempotentRequest, claim_token: uuid.UUID
) -> bool:
    """Take an in-progress claim whose lease has expired, in one statement; True if taken.

    Method, path, and body hash are part of the condition, so a request that differs from the
    one that claimed the key can never take it over (B-40), and the lease condition means that of
    two simultaneous takeovers the second finds a live lease and updates nothing.
    """
    statement = (
        update(keys)
        .where(
            keys.c.key == request.key,
            keys.c.user_id == request.user_id,
            keys.c.request_method == request.method,
            keys.c.request_path == request.path,
            keys.c.request_body_hash == request.body_hash,
            keys.c.state == IdempotencyKeyState.IN_PROGRESS.value,
            keys.c.locked_until < func.now(),
        )
        .values(locked_until=func.now() + LEASE, claim_token=claim_token)
        .returning(keys.c.key)
    )
    return (await connection.execute(statement)).first() is not None


async def complete_idempotency_key(
    connection: AsyncConnection,
    request: IdempotentRequest,
    claim_token: uuid.UUID,
    response: StoredResponse,
) -> bool:
    """Store the response on the claim this request still holds; False if it was taken over."""
    statement = (
        update(keys)
        .where(
            keys.c.key == request.key,
            keys.c.user_id == request.user_id,
            keys.c.claim_token == claim_token,
        )
        .values(
            state=IdempotencyKeyState.COMPLETED.value,
            status_code=response.status_code,
            response_body=response.json_body,
            response_body_bytes=response.body,
            response_content_type=response.content_type,
            response_headers=[list(header) for header in response.headers],
        )
        .returning(keys.c.key)
    )
    return (await connection.execute(statement)).first() is not None


async def release_idempotency_key(
    connection: AsyncConnection, request: IdempotentRequest, claim_token: uuid.UUID
) -> None:
    """Delete the claim this request still holds, so a retry runs; a superseded claim stays."""
    statement = delete(keys).where(
        keys.c.key == request.key,
        keys.c.user_id == request.user_id,
        keys.c.claim_token == claim_token,
    )
    await connection.execute(statement)


async def delete_stale_idempotency_keys_batch(connection: AsyncConnection, batch_size: int) -> int:
    """Delete up to `batch_size` keys past their retention and return how many went."""
    stale_batch = (
        select(keys.c.key, keys.c.user_id)
        .where(keys.c.created_at < func.now() - IDEMPOTENCY_KEY_RETENTION)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("stale_batch")
        .prefix_with("MATERIALIZED")
    )
    result = await connection.execute(
        delete(keys).where(keys.c.key == stale_batch.c.key, keys.c.user_id == stale_batch.c.user_id)
    )
    return result.rowcount
