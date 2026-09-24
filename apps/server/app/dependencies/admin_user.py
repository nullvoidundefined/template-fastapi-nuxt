"""Admits only an administrator, on top of the ordinary session resolution.

`require_admin` depends on `get_current_user`, so a request without a usable session is still
refused with 401 before its role is ever judged: an unknown caller and an unprivileged one are
different answers, and a client signs in for the first but not for the second. The role is the
one read from the users row in the same lookup that resolved the session, never one the client
supplied.
"""

from typing import Annotated

import structlog
from fastapi import Depends

from app.constants.error_codes import ErrorCode
from app.constants.user_roles import UserRole
from app.dependencies.current_user import AuthenticatedUser, CurrentUser
from app.errors import ForbiddenError

ADMIN_REQUIRED_MESSAGE = "Administrator access is required"

logger = structlog.get_logger(__name__)


class AdminRequiredError(ForbiddenError):
    """The caller is signed in but is not an administrator."""

    def __init__(self) -> None:
        """Answer 403 with the registry's admin-required code."""
        super().__init__(ErrorCode.AUTH_ADMIN_REQUIRED, ADMIN_REQUIRED_MESSAGE)


async def require_admin(current: CurrentUser) -> AuthenticatedUser:
    """Return the signed-in user when that user is an admin, and refuse everyone else."""
    if current.user.role != UserRole.ADMIN:
        logger.warning("admin_access_refused", user_id=str(current.user.id))
        raise AdminRequiredError
    return current


AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
