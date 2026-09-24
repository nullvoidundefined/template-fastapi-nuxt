"""Reads one page of users and the total beside it, for the admin user list.

The page and the count are read in the request's one transaction, so the total a page reports is
the total at the moment its rows were read rather than a moment later.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.repositories.users import count_users, list_users_page


@dataclass(slots=True, frozen=True)
class UsersPage:
    """One page of user rows and how many users exist in all."""

    rows: list[Row[Any]]
    total: int


async def list_users(connection: AsyncConnection, limit: int, offset: int) -> UsersPage:
    """Return the requested page of users together with the total count."""
    rows = await list_users_page(connection, limit, offset)
    total = await count_users(connection)
    return UsersPage(rows=rows, total=total)
