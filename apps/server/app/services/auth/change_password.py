"""Replaces a password and signs out every other session of the user.

Every other session, not every session. A password change is usually made because a session
somewhere else should stop working, and signing the caller out as well turns a security action
into a logout, which trains people not to take it.

The row lock comes first here for the same reason it does in sign-in, and the two together are
what make the pair safe: a sign-in that verified the old password cannot commit a new session
after this has revoked the old ones, because it cannot hold the row at the same time.
"""

import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import hash_password, verify_password
from app.db.tables import user_sessions, users
from app.repositories.users import lock_user_by_id
from app.services.auth.sign_in_user import InvalidCredentialsError


async def change_password(
    connection: AsyncConnection,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
    """Replace the password after proving the caller knows it, then revoke the other sessions.

    The account is named by the id the session resolved to, never by the address on it. An
    address is expected to change, and an authorization decision re-derived from a mutable
    attribute is only accidentally correct.
    """
    user = await lock_user_by_id(connection, user_id)
    stored_hash = user.password_hash if user else None
    if not await verify_password(current_password, stored_hash) or user is None:
        raise InvalidCredentialsError
    await connection.execute(
        update(users)
        .where(users.c.id == user.id)
        .values(password_hash=await hash_password(new_password))
    )
    await revoke_other_sessions(connection, user.id, session_id)


async def revoke_other_sessions(
    connection: AsyncConnection, user_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """Delete every session this user holds except the one making the request."""
    statement = delete(user_sessions).where(
        user_sessions.c.user_id == user_id,
        user_sessions.c.id != session_id,
    )
    await connection.execute(statement)
