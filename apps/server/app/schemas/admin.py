"""Response models and page bounds for the admin routes.

`AdminUserData` names its four fields rather than spreading a row, so a column added to `users`
later, or the password hash that is already there, can never reach the response by accident. B-19
asserts the exact key set for the same reason.
"""

from pydantic import AwareDatetime, BaseModel
from pydantic.types import UUID4

from app.constants.user_roles import UserRole

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


class AdminUserData(BaseModel):
    """One user as an administrator sees it: never the password hash."""

    id: UUID4
    email: str
    role: UserRole
    created_at: AwareDatetime


class PageMeta(BaseModel):
    """Where a page sits in the whole list: the total, and the bounds that produced this page."""

    total: int
    limit: int
    offset: int


class AdminUserListResponse(BaseModel):
    """The `{ data, meta }` envelope around one page of users."""

    data: list[AdminUserData]
    meta: PageMeta
