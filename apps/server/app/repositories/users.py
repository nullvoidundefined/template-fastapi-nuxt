"""Data access for the users table.

Every lookup normalizes the address the same way, and that is the point of routing them through
one module. The unique index is on `lower(email)`, so an account created as `A@x.com` is found
by `a@x.com`; a lookup that passed the submitted case straight through would fail to find an
account that exists, and would then register a duplicate the index refuses.

`lock_user_for_update` is the same lookup holding a row lock. It exists because verifying a
password and acting on the result are two statements, and a password change can commit between
them: a login that verified an old password could otherwise insert a live session after the change
that was meant to revoke every session had already run. Taking the lock first serializes the two
per user, and costs nothing when nobody is contending.

`lock_user_by_id` holds the same lock for a caller that already knows which account it is acting
on, which every authenticated request does. An address is a value a user is expected to change,
so re-deriving the subject of an authorization decision from it makes that decision depend on a
mutable attribute; the id the session resolved to is the account itself.
"""

import uuid
from typing import Any

from sqlalchemy import Row, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.tables import users


def normalize_email(email: str) -> str:
    """Return the address as it is compared: trimmed of surrounding space and lowercased."""
    return email.strip().lower()


async def get_user_by_email(connection: AsyncConnection, email: str) -> Row[Any] | None:
    """Return the user whose folded address matches, or None when there is no such account.

    Compared as `lower(email) = :email` rather than with `ILIKE`, which would read the underscore
    and percent in an address as wildcards and would not use the functional unique index.
    """
    statement = select(users).where(func.lower(users.c.email) == normalize_email(email))
    return (await connection.execute(statement)).one_or_none()


async def lock_user_for_update(connection: AsyncConnection, email: str) -> Row[Any] | None:
    """Return the same user as `get_user_by_email`, holding its row lock until this commits.

    The caller must already be inside a transaction, which `get_connection` guarantees for a
    request. The lock is released by that transaction's commit or rollback, never by this function.
    """
    statement = (
        select(users).where(func.lower(users.c.email) == normalize_email(email)).with_for_update()
    )
    return (await connection.execute(statement)).one_or_none()


async def lock_user_by_id(connection: AsyncConnection, user_id: uuid.UUID) -> Row[Any] | None:
    """Return the user with this id, holding its row lock until the transaction ends.

    The same lock as `lock_user_for_update`, taken on the identity the caller already holds. A
    sign-in cannot use it, because it has only the submitted address until the row is found.
    """
    statement = select(users).where(users.c.id == user_id).with_for_update()
    return (await connection.execute(statement)).one_or_none()


async def list_users_page(connection: AsyncConnection, limit: int, offset: int) -> list[Row[Any]]:
    """Return one page of users as id, email, role, and created_at, oldest first.

    The columns are named rather than `select(users)`, so the password hash is never read into a
    row that some caller could later serialize. The id breaks ties between users created in the
    same instant, which keeps the order stable from one page to the next.
    """
    statement = (
        select(users.c.id, users.c.email, users.c.role, users.c.created_at)
        .order_by(users.c.created_at, users.c.id)
        .limit(limit)
        .offset(offset)
    )
    return list(await connection.execute(statement))


async def count_users(connection: AsyncConnection) -> int:
    """Return how many users exist, the total a paginated list reports beside its page."""
    user_count = await connection.scalar(select(func.count()).select_from(users))
    return int(user_count or 0)


async def update_password_hash(
    connection: AsyncConnection, user_id: uuid.UUID, password_hash: str
) -> None:
    """Store a new bcrypt hash for this user; the caller hashes, this only writes."""
    statement = update(users).where(users.c.id == user_id).values(password_hash=password_hash)
    await connection.execute(statement)
