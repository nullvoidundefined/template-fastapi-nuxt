"""Spends a password-reset token: sets the new password and signs out every session.

Every session, unlike a password change. A reset is made by someone who could not sign in, so
there is no current session to spare, and the usual reason for a reset is that somebody else may
hold one.

The token is consumed before the password is hashed. Consumption is the one atomic statement that
decides whether this submission wins, so a losing or invalid submission is refused without paying
for bcrypt, and everything after it runs in the same transaction, so a failure after consumption
rolls the consumption back and the link still works.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from app.constants.error_codes import ErrorCode
from app.core.security import hash_password, hash_token
from app.errors import AppError
from app.repositories.user_password_resets import consume_password_reset
from app.repositories.user_sessions import delete_user_sessions
from app.repositories.users import update_password_hash

INVALID_RESET_LINK_MESSAGE = "That reset link is invalid or has expired"


class ResetTokenInvalidError(AppError):
    """The token is unknown, already used, expired, or superseded, and the client learns only that.

    One answer for all four, because telling them apart would tell a caller which tokens once
    existed.
    """

    def __init__(self) -> None:
        """Answer 400 with the one code every unusable token shares."""
        super().__init__(400, ErrorCode.AUTH_RESET_TOKEN_INVALID, INVALID_RESET_LINK_MESSAGE)


async def reset_password(
    connection: AsyncConnection, raw_token: str, new_password: str
) -> uuid.UUID:
    """Consume the token, store the new password, sign out every session, and return the user."""
    user_id = await consume_password_reset(connection, hash_token(raw_token))
    if user_id is None:
        raise ResetTokenInvalidError
    await update_password_hash(connection, user_id, await hash_password(new_password))
    await delete_user_sessions(connection, user_id)
    return user_id
