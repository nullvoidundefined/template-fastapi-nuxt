"""Verifies a password and opens a session, refusing both failures identically.

The row lock comes first, before the password is even read. Verifying a password and acting on the
result are two statements, and a password change can commit between them: a sign-in that verified
the old password would otherwise insert a live session after the change that was meant to revoke
every session had already run. Taking the lock first serializes the two per user.

An unknown address and a wrong password answer the same code, and the unknown path still runs a
real comparison, which `verify_password` guarantees by having no branch at all. Answering
differently, or answering faster, tells an attacker which addresses have accounts.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import func

from app.constants.error_codes import ErrorCode
from app.constants.session import SESSION_TTL
from app.core.security import generate_session_token, verify_password
from app.db.tables import user_sessions
from app.errors import AppError
from app.repositories.user_sessions import create_session
from app.repositories.users import lock_user_for_update

INVALID_CREDENTIALS_MESSAGE = "That email address and password do not match an account"


class InvalidCredentialsError(AppError):
    """The address is unknown or the password is wrong, and the client is told only that."""

    def __init__(self) -> None:
        """Answer 401 with the one code both failures share."""
        super().__init__(401, ErrorCode.AUTH_INVALID_CREDENTIALS, INVALID_CREDENTIALS_MESSAGE)


@dataclass(slots=True, frozen=True)
class SignedInUser:
    """The account that signed in and the raw token its cookie carries."""

    id: uuid.UUID
    email: str
    raw_token: str


async def sign_in_user(connection: AsyncConnection, email: str, password: str) -> SignedInUser:
    """Open a session for the account, or refuse without saying which half was wrong."""
    user = await lock_user_for_update(connection, email)
    stored_hash = user.password_hash if user else None
    # Bound to a name on its own line rather than written into the guard. Both forms behave
    # identically today, but an operand inside a conditional invites the reordering that lets an
    # unknown address skip bcrypt, which is the enumeration oracle B-11 exists to close.
    comparison_matched = await verify_password(password, stored_hash)
    if not comparison_matched or user is None:
        raise InvalidCredentialsError
    await delete_expired_sessions(connection, user.id)
    raw_token, token_hash = generate_session_token()
    await create_session(connection, user.id, token_hash, datetime.now(UTC) + SESSION_TTL)
    return SignedInUser(id=user.id, email=user.email, raw_token=raw_token)


async def delete_expired_sessions(connection: AsyncConnection, user_id: uuid.UUID) -> None:
    """Remove this user's dead sessions, leaving every live one alone.

    Signing in is the natural moment to do this: the rows are this user's, the transaction is
    already open, and the hourly job in slice 08 then has less to sweep.
    """
    statement = delete(user_sessions).where(
        user_sessions.c.user_id == user_id,
        user_sessions.c.expires_at <= func.now(),
    )
    await connection.execute(statement)
