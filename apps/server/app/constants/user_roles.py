"""The permission levels a user can hold, stored as the Postgres enum `user_role`.

A role rather than an `is_admin` boolean, because a boolean cannot grow a third level. The values
are the enum's labels, so the column, the API, and this registry spell each role the same way.
Every new account is a `member`; only an operator promotes one to `admin`.
"""

from enum import StrEnum

USER_ROLE_ENUM_NAME = "user_role"


class UserRole(StrEnum):
    """Every role the `user_role` enum holds, in its declared order."""

    MEMBER = "member"
    ADMIN = "admin"
