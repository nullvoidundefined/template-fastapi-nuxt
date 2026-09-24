"""The admin routes, every one of them behind `require_admin`.

The dependency sits on the router rather than on each route, so a route added here later is
guarded by being in this module rather than by being remembered. The Express template exports its
admin guard but mounts it on nothing; this router is the one endpoint the port adds for the guard
to protect and the admin page to show.

The page bounds are query parameters validated by FastAPI, so an out-of-range or malformed value
answers 400 `INPUT_VALIDATION_ERROR` through the envelope before any query runs.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies.admin_user import require_admin
from app.dependencies.current_user import RequestConnection
from app.schemas.admin import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    AdminUserData,
    AdminUserListResponse,
    PageMeta,
)
from app.services.admin.list_users import list_users

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)]


@router.get("/users", response_model=AdminUserListResponse)
async def read_users(
    connection: RequestConnection,
    limit: PageLimit = DEFAULT_PAGE_LIMIT,
    offset: PageOffset = 0,
) -> AdminUserListResponse:
    """Answer one page of users, oldest first, with the total and the bounds applied."""
    page = await list_users(connection, limit, offset)
    return AdminUserListResponse(
        data=[AdminUserData.model_validate(row, from_attributes=True) for row in page.rows],
        meta=PageMeta(total=page.total, limit=limit, offset=offset),
    )
