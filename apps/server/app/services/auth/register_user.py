"""Creates an account and the session that signs it in.

The duplicate is caught around the insert rather than prevented by a preceding select. A select
that finds nothing and an insert that follows it are two statements, and a second registration for
the same address can commit between them; the unique index on `lower(email)` is what actually
decides, so the catch belongs where the index speaks.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.constants.error_codes import ErrorCode
from app.constants.session import SESSION_TTL
from app.constants.user_roles import UserRole
from app.core.security import generate_session_token, hash_password
from app.db.tables import users
from app.errors import ConflictError
from app.repositories.user_sessions import create_session
from app.repositories.users import normalize_email

EMAIL_ALREADY_REGISTERED_MESSAGE = "That email address is already registered"
# Postgres raises this for any unique violation, including the functional index on lower(email).
UNIQUE_VIOLATION_SQLSTATE = "23505"


@dataclass(slots=True, frozen=True)
class RegisteredUser:
    """The new account and the raw token its cookie carries."""

    id: uuid.UUID
    email: str
    role: UserRole
    raw_token: str


async def register_user(connection: AsyncConnection, email: str, password: str) -> RegisteredUser:
    """Create the account and its first session, or refuse a duplicate address."""
    normalized_email = normalize_email(email)
    password_hash = await hash_password(password)
    user_id, role = await insert_user(connection, normalized_email, password_hash)
    raw_token, token_hash = generate_session_token()
    await create_session(connection, user_id, token_hash, datetime.now(UTC) + SESSION_TTL)
    return RegisteredUser(id=user_id, email=normalized_email, role=role, raw_token=raw_token)


async def insert_user(
    connection: AsyncConnection, email: str, password_hash: str
) -> tuple[uuid.UUID, UserRole]:
    """Insert the account and return its id and the role the column defaulted it to.

    The role is read back rather than assumed, so the response states what the row holds. The
    index's refusal of a duplicate address is translated into the registry's code.
    """
    statement = (
        insert(users)
        .values(email=email, password_hash=password_hash)
        .returning(users.c.id, users.c.role)
    )
    try:
        inserted = (await connection.execute(statement)).one()
    except IntegrityError as err:
        if getattr(err.orig, "sqlstate", None) != UNIQUE_VIOLATION_SQLSTATE:
            raise
        raise ConflictError(
            code=ErrorCode.AUTH_EMAIL_ALREADY_REGISTERED,
            message=EMAIL_ALREADY_REGISTERED_MESSAGE,
        ) from err
    return uuid.UUID(str(inserted.id)), UserRole(inserted.role)
