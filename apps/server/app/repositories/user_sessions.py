"""Data access for the user_sessions table.

The table never sees a raw token. `create_session` takes the SHA-256 that
`app.core.security.generate_session_token` produced alongside it, so the only copy of the raw
value is the one in the client's cookie.

`touch_session` is a conditional UPDATE rather than a read and a write. Every authenticated
request would otherwise write a row, which is a write per request for a column nothing reads at
that resolution, and two simultaneous requests deciding from the same read would both write. The
condition lives in the statement, so Postgres evaluates it against the row it has locked and the
second request updates nothing.
"""

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func, text

from app.db.tables import user_sessions

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
