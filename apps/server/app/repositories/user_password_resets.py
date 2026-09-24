"""Data access for the user_password_resets table.

The table never sees a raw token, only the SHA-256 that `generate_password_reset_token` produced
alongside it, so the only copy of the raw value is the one in the email.

`replace_password_reset` deletes the user's earlier unused resets before inserting the new one,
so only the latest link works. Both statements run on the caller's connection, inside the
caller's transaction, so no reader ever sees the user with two live resets or with none.

`consume_password_reset` is one conditional UPDATE rather than a read and a write. Two
submissions of the same token that each read the row as unused would both succeed; with the
condition inside the statement, Postgres evaluates it against the row it has locked, and the
second submission updates nothing and gets nothing back.
"""

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

from app.db.tables import user_password_resets


async def replace_password_reset(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> None:
    """Retire this user's unused resets and insert the new one; only its hash is stored."""
    await connection.execute(
        delete(user_password_resets).where(
            user_password_resets.c.user_id == user_id,
            user_password_resets.c.used_at.is_(None),
        )
    )
    await connection.execute(
        user_password_resets.insert().values(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
    )


async def consume_password_reset(connection: AsyncConnection, token_hash: str) -> uuid.UUID | None:
    """Mark the reset used and return its user, or None when it is unknown, spent, or expired.

    The whole decision is the WHERE clause of one statement, so two concurrent submissions of one
    token cannot both be told yes.
    """
    statement = (
        update(user_password_resets)
        .where(
            user_password_resets.c.token_hash == token_hash,
            user_password_resets.c.used_at.is_(None),
            user_password_resets.c.expires_at > func.now(),
        )
        .values(used_at=func.now())
        .returning(user_password_resets.c.user_id)
    )
    user_id = await connection.scalar(statement)
    return cast("uuid.UUID | None", user_id)
