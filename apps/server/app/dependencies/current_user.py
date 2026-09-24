"""Turns a session cookie into the signed-in user, or says precisely why it cannot.

Two resolvers, because two callers need different things from the same lookup.

`get_current_user` is what a protected route declares. It raises, and it distinguishes a request
that carried no usable session from one whose session has expired: a client that knows the
difference can retry a sign-in rather than treating both as the same failure. A query filtered on
the expiry alone cannot tell them apart, since an expired row and an unknown token both return
nothing, so the row is fetched first and its expiry judged afterwards.

`resolve_current_user` is what logout declares. It never raises and returns None for anything it
cannot resolve, because logging out must answer the same way whether or not a session existed.

Both return the session id alongside the user. A password change signs out every session except
the one making the request, and it cannot identify that one from the user alone.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import Depends
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.requests import Request

from app.constants.error_codes import ErrorCode
from app.constants.session import SESSION_COOKIE_NAME
from app.constants.user_roles import UserRole
from app.core.security import hash_token
from app.db.session import get_connection
from app.errors import AppError
from app.repositories.user_sessions import find_session_with_user

# Declared here rather than at each route, so a route that takes the signed-in user gets the
# request's transaction with it. Without the Depends marker FastAPI reads the parameter as
# request data and refuses to register the route at all.
RequestConnection = Annotated[AsyncConnection, Depends(get_connection, scope="function")]

AUTH_REQUIRED_MESSAGE = "Authentication is required"
AUTH_SESSION_EXPIRED_MESSAGE = "That session has expired"

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class SessionUser:
    """The signed-in user, carrying only what a caller of this dependency may see."""

    id: uuid.UUID
    email: str
    role: UserRole


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    """One resolved session: the user it belongs to and the id of the session itself."""

    user: SessionUser
    session_id: uuid.UUID


class AuthRequiredError(AppError):
    """The request carried no session, or one no session row matches."""

    def __init__(self) -> None:
        """Answer 401 with the code a client treats as "sign in"."""
        super().__init__(401, ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)


class SessionExpiredError(AppError):
    """The request named a real session whose lifetime has passed."""

    def __init__(self) -> None:
        """Answer 401 with the code a client treats as "sign in again"."""
        super().__init__(401, ErrorCode.AUTH_SESSION_EXPIRED, AUTH_SESSION_EXPIRED_MESSAGE)


async def get_current_user(request: Request, connection: RequestConnection) -> AuthenticatedUser:
    """Return the signed-in user, raising when the session is absent, unknown, or expired."""
    session_row = await read_session_row(request, connection)
    if session_row is None:
        raise AuthRequiredError
    if session_row.expires_at <= datetime.now(UTC):
        logger.info("session_expired", session_id=str(session_row.session_id))
        raise SessionExpiredError
    return build_authenticated_user(session_row)


async def resolve_current_user(
    request: Request, connection: RequestConnection
) -> AuthenticatedUser | None:
    """Return the signed-in user, or None for anything that does not resolve to a live session."""
    session_row = await read_session_row(request, connection)
    if session_row is None or session_row.expires_at <= datetime.now(UTC):
        return None
    return build_authenticated_user(session_row)


async def read_session_row(request: Request, connection: AsyncConnection) -> Row[Any] | None:
    """Return the session joined to its user for the request's cookie, expiry not yet judged."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None
    return await find_session_with_user(connection, hash_token(raw_token))


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OptionalCurrentUser = Annotated[AuthenticatedUser | None, Depends(resolve_current_user)]


def build_authenticated_user(session_row: Row[Any]) -> AuthenticatedUser:
    """Bind the user id into the log context and return the resolved session."""
    structlog.contextvars.bind_contextvars(user_id=str(session_row.user_id))
    return AuthenticatedUser(
        user=SessionUser(
            id=session_row.user_id, email=session_row.email, role=UserRole(session_row.role)
        ),
        session_id=session_row.session_id,
    )
