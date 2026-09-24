"""Data access for the user_sessions table.

The table never sees a raw token. `create_session` takes the SHA-256 that
`app.core.security.generate_session_token` produced alongside it, so the only copy of the raw
value is the one in the client's cookie.

`touch_session` is a conditional UPDATE rather than a read and a write. Every authenticated
request would otherwise write a row, which is a write per request for a column nothing reads at
that resolution, and two simultaneous requests deciding from the same read would both write. The
condition lives in the statement, so Postgres evaluates it against the row it has locked and the
second request updates nothing.

`find_session_with_user` is the one lookup that turns a cookie's token hash into a session and its
user. The session dependency and the idempotency middleware both resolve a cookie through it, so
the two can never disagree about who a request belongs to.

`delete_expired_sessions_batch` is the hourly cleanup job's statement for this table. It deletes
at most one batch of sessions whose `expires_at` has passed, found through the `expires_at` index,
and skips any row another transaction holds, so the cleanup never waits on a request's write.
The batch is a materialized CTE rather than an `IN (SELECT ... LIMIT)` subquery, because Postgres
may run such a subquery more than once in one DELETE, and each run locks and returns a fresh set
of rows, so the statement would delete more than one batch.
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Row, delete, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func, text

from app.db.tables import user_sessions, users

# A session's last_seen_at is read by an operator and by the cleanup job, neither of which cares
# about the difference between four minutes ago and now. Writing at most this often turns a write
# per request into a write per interval per session.
LAST_SEEN_INTERVAL = text("interval '5 minutes'")


async def create_session(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> uuid.UUID:
    """Insert one session for this user and return its id; only the token's hash is stored."""
    statement = (
        user_sessions.insert()
        .values(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        .returning(user_sessions.c.id)
    )
    session_id = await connection.scalar(statement)
    # RETURNING on an INSERT of one row always yields the id; the cast documents that for the
    # type checker, which cannot see that the statement inserts exactly one row.
    return cast("uuid.UUID", session_id)


async def find_session_with_user(connection: AsyncConnection, token_hash: str) -> Row[Any] | None:
    """Return the session joined to its user for this token hash, its expiry not yet judged.

    The expiry is deliberately not in the WHERE clause. Filtering on it here would make an expired
    session indistinguishable from a token that never existed, and the session dependency answers
    those two differently.
    """
    statement = (
        select(
            user_sessions.c.id.label("session_id"),
            user_sessions.c.expires_at,
            users.c.id.label("user_id"),
            users.c.email,
            users.c.role,
        )
        .join_from(user_sessions, users, user_sessions.c.user_id == users.c.id)
        .where(user_sessions.c.token_hash == token_hash)
    )
    return (await connection.execute(statement)).one_or_none()


async def touch_session(connection: AsyncConnection, session_id: uuid.UUID) -> None:
    """Move last_seen_at to now, but only when it is already older than the interval.

    The condition is part of the statement rather than a decision taken after a read, so two
    requests arriving together cannot both conclude the row is stale and both write it.
    """
    statement = (
        update(user_sessions)
        .where(
            user_sessions.c.id == session_id,
            user_sessions.c.last_seen_at < func.now() - LAST_SEEN_INTERVAL,
        )
        .values(last_seen_at=func.now())
    )
    await connection.execute(statement)


async def delete_session(connection: AsyncConnection, session_id: uuid.UUID) -> None:
    """Remove one session, which is what signing out of this browser means."""
    await connection.execute(delete(user_sessions).where(user_sessions.c.id == session_id))


async def delete_user_sessions(connection: AsyncConnection, user_id: uuid.UUID) -> None:
    """Remove every session this user holds, which signs the account out of every browser."""
    await connection.execute(delete(user_sessions).where(user_sessions.c.user_id == user_id))


async def delete_expired_sessions_batch(connection: AsyncConnection, batch_size: int) -> int:
    """Delete up to `batch_size` sessions whose expiry has passed and return how many went."""
    expired_batch = (
        select(user_sessions.c.id)
        .where(user_sessions.c.expires_at <= func.now())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("expired_batch")
        .prefix_with("MATERIALIZED")
    )
    result = await connection.execute(
        delete(user_sessions).where(user_sessions.c.id == expired_batch.c.id)
    )
    return result.rowcount
