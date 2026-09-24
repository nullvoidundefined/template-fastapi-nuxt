"""Data access for request_idempotency_keys: claim, read, take over, complete, release.

Every statement here decides in the database rather than in Python. A claim is one
`INSERT ... ON CONFLICT`, so two simultaneous requests cannot both insert; a takeover is one
conditional `UPDATE ... RETURNING`, so two takeovers of one expired lease cannot both win; and
every lease and window comparison uses Postgres's `now()`, so the application's clock never
enters into it. The completion and the release both carry `claim_token = :mine`, which is what
stops a holder that was taken over from overwriting or deleting the claim that superseded it.

The caller runs each function in its own short transaction, outside the request's transaction,
so other requests see a claim the moment it is taken.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Row, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

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
    status_code: int,
    response_body: object,
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
            status_code=status_code,
            response_body=response_body,
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
