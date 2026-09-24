"""Issues a password reset for an address, or nothing when no account uses it.

Called by the email job rather than by the route. The route answers the same way for a known and
an unknown address, so the lookup that tells them apart happens here, in the worker, where no
response can reveal it.

The user's row is locked first, for the reason sign-in locks it: issuing is a delete followed by
an insert, and two issues for one user running side by side could otherwise each delete before
either inserts, leaving two live links where only the latest should work.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from app.constants.password_reset import PASSWORD_RESET_TTL
from app.core.security import generate_password_reset_token
from app.repositories.user_password_resets import replace_password_reset
from app.repositories.users import lock_user_for_update


@dataclass(slots=True, frozen=True)
class IssuedPasswordReset:
    """The account a reset was issued for and the raw token its email carries."""

    user_id: uuid.UUID
    email: str
    raw_token: str


async def issue_password_reset(
    connection: AsyncConnection, email: str
) -> IssuedPasswordReset | None:
    """Store a fresh reset for the account at this address, retiring any unused earlier one.

    Returns None for an address no account uses, so the caller sends nothing.
    """
    user = await lock_user_for_update(connection, email)
    if user is None:
        return None
    raw_token, token_hash = generate_password_reset_token()
    await replace_password_reset(
        connection, user.id, token_hash, datetime.now(UTC) + PASSWORD_RESET_TTL
    )
    return IssuedPasswordReset(user_id=user.id, email=user.email, raw_token=raw_token)
