"""The routes that create, read and end a session, and the two that reset a password.

Each one validates its body, calls a single service, and shapes a response. The orchestration
lives in `app/services/auth/` because registering, signing in and changing a password are each
several steps against several tables, and a router that carried them would have to be unpicked
the first time anything else needed one.

`logout` takes the non-raising resolver rather than the strict dependency, because B-31 requires
204 whether or not a session existed. A route that raised for an absent cookie would make logging
out fail for exactly the person who most wants it to succeed.

`forgot-password` is the one route that calls no service. It enqueues the email job and answers,
because the lookup that would tell a known address from an unknown one belongs in the worker,
where no response or timing can reveal it.
"""

import structlog
from fastapi import APIRouter, Response, status

from app.constants.job_names import RESET_EMAIL_JOB_NAME
from app.constants.user_roles import UserRole
from app.core.session_cookie import clear_session_cookie, set_session_cookie
from app.dependencies.current_user import CurrentUser, OptionalCurrentUser, RequestConnection
from app.dependencies.job_queue import RequestJobQueue
from app.dependencies.settings import RequestSettings
from app.repositories.user_sessions import delete_session
from app.schemas.auth import (
    AuthenticatedUserData,
    AuthenticatedUserResponse,
    ChangePasswordRequest,
    ForgotPasswordData,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.services.auth.change_password import change_password
from app.services.auth.register_user import register_user
from app.services.auth.reset_password import reset_password
from app.services.auth.sign_in_user import sign_in_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])
logger = structlog.get_logger(__name__)

RESET_REQUESTED_MESSAGE = "If an account uses that address, a reset link is on its way"


def build_user_response(user_id: object, email: str, role: UserRole) -> AuthenticatedUserResponse:
    """Shape the one body every successful auth route answers with."""
    return AuthenticatedUserResponse(data=AuthenticatedUserData(id=user_id, email=email, role=role))


@router.post(
    "/register",
    response_model=AuthenticatedUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    response: Response,
    connection: RequestConnection,
    settings: RequestSettings,
) -> AuthenticatedUserResponse:
    """Create an account, sign it in, and set the session cookie."""
    registered = await register_user(connection, body.email, body.password)
    set_session_cookie(response, registered.raw_token, settings.environment)
    logger.info("user_registered", user_id=str(registered.id))
    return build_user_response(registered.id, registered.email, registered.role)


@router.post("/login", response_model=AuthenticatedUserResponse)
async def login(
    body: LoginRequest,
    response: Response,
    connection: RequestConnection,
    settings: RequestSettings,
) -> AuthenticatedUserResponse:
    """Open a session for an existing account and set the session cookie."""
    signed_in = await sign_in_user(connection, body.email, body.password)
    set_session_cookie(response, signed_in.raw_token, settings.environment)
    logger.info("user_signed_in", user_id=str(signed_in.id))
    return build_user_response(signed_in.id, signed_in.email, signed_in.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    connection: RequestConnection,
    settings: RequestSettings,
    current: OptionalCurrentUser,
) -> Response:
    """End the session if there is one, and clear the cookie either way.

    No injected `Response` is declared. FastAPI assigns a returned `Response` instance directly
    and never merges the injected one's headers, so anything written to it here would be dropped
    without a test noticing, on the one route whose whole job is to get a cookie header right.
    """
    if current is not None:
        await delete_session(connection, current.session_id)
        logger.info("user_signed_out", user_id=str(current.user.id))
    empty = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(empty, settings.environment)
    return empty


@router.get("/me", response_model=AuthenticatedUserResponse)
async def read_me(current: CurrentUser) -> AuthenticatedUserResponse:
    """Answer the signed-in user's identity and role, and 401 without a usable session."""
    return build_user_response(current.user.id, current.user.email, current.user.role)


@router.patch("/me", response_model=AuthenticatedUserResponse)
async def change_my_password(
    body: ChangePasswordRequest,
    connection: RequestConnection,
    current: CurrentUser,
) -> AuthenticatedUserResponse:
    """Replace the password after proving the current one, signing out every other session."""
    await change_password(
        connection,
        current.user.id,
        current.session_id,
        body.current_password,
        body.new_password,
    )
    logger.info("user_password_changed", user_id=str(current.user.id))
    return build_user_response(current.user.id, current.user.email, current.user.role)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def request_password_reset(
    body: ForgotPasswordRequest, job_queue: RequestJobQueue
) -> ForgotPasswordResponse:
    """Enqueue the reset email and answer 200, whether or not an account uses the address.

    The route never looks the address up. The job does, in the worker, so the response and the
    work this request causes are identical for a known and an unknown address (B-14).
    """
    # The request's ID travels with the job, so the worker's work for this request is correlated
    # with it (R-341).
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    await job_queue.enqueue_job(RESET_EMAIL_JOB_NAME, body.email, request_id)
    return ForgotPasswordResponse(data=ForgotPasswordData(message=RESET_REQUESTED_MESSAGE))


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password_with_token(
    body: ResetPasswordRequest, connection: RequestConnection
) -> Response:
    """Set a new password from an emailed token and sign the account out everywhere."""
    user_id = await reset_password(connection, body.token, body.password)
    logger.info("user_password_reset", user_id=str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
