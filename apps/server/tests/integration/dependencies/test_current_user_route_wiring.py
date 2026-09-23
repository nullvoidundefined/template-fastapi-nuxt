"""Pin that a real route can declare the session resolvers and that the app answers through them.

The resolvers were reviewable as correct and still unusable. Both declared `connection` as a bare
`AsyncConnection` with no `Depends` marker, so FastAPI read the parameter as request data and
refused to build the route at all: every route that took the signed-in user would have failed
where it was declared, in production, on a request the process never got to serve. Nothing caught
it because every existing test calls the resolvers as plain functions and hands them a connection
it opened itself, which is precisely the call FastAPI never makes.

These tests therefore never call a resolver. They build the application through the same public
factory uvicorn runs, mount a test-only router whose routes declare `Depends(get_current_user)`
and `Depends(resolve_current_user)`, and drive it over HTTP against the real migrated Postgres.
Removing the `Depends` marker from either signature fails them, at registration when FastAPI
rejects the parameter and at request time otherwise, because the router is built inside the test
body rather than at import.

The negative case is the same route without a usable cookie: absent, malformed, and oversized
cookie values all have to answer 401 `AUTH_REQUIRED` through the error envelope rather than 500.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

CURRENT_USER_PATH = "/test-only/current-user"
RESOLVED_USER_PATH = "/test-only/resolved-user"

PASSWORD_HASH = "-".join(("test", "hash"))
# Long enough to be a payload rather than a typo, and built from a repeated unit so that no
# credential-shaped literal appears in this file (R-108).
OVERSIZED_COOKIE_VALUE = "a" * 4096
MALFORMED_COOKIE_VALUE = "; ".join(("not a cookie value", "DROP TABLE user_sessions --"))

INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
DELETE_USER_SQL = text("DELETE FROM users WHERE id = :id")
INSERT_SESSION_SQL = text(
    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
    "VALUES (:user_id, :token_hash, :expires_at) RETURNING id"
)

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]
CurrentUserAppFactory = Callable[[], tuple[FastAPI, AbstractAsyncContextManager[httpx.AsyncClient]]]


def build_test_only_router() -> APIRouter:
    """Return routes that take the signed-in user the way a real protected route would.

    Built inside a test body rather than at import, so a resolver FastAPI cannot accept as a
    dependency is a failing test naming the behavior rather than a collection error.
    """
    from app.dependencies.current_user import (  # noqa: PLC0415
        AuthenticatedUser,
        get_current_user,
        resolve_current_user,
    )

    router = APIRouter()
    RequiredUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
    OptionalUser = Annotated[AuthenticatedUser | None, Depends(resolve_current_user)]

    @router.get(CURRENT_USER_PATH)
    async def read_current_user(current_user: RequiredUser) -> dict[str, str]:
        """Answer with the identity the dependency resolved, or let the dependency raise."""
        return describe_user(current_user)

    @router.get(RESOLVED_USER_PATH)
    async def read_resolved_user(current_user: OptionalUser) -> dict[str, str | None]:
        """Answer with the identity the logout resolver found, or with nulls when it found none."""
        if current_user is None:
            return {"email": None, "user_id": None, "session_id": None}
        return dict(describe_user(current_user))

    return router


def describe_user(current_user: Any) -> dict[str, str]:
    """Render a resolved session as the body a route would return for it."""
    return {
        "email": current_user.user.email,
        "user_id": str(current_user.user.id),
        "session_id": str(current_user.session_id),
    }


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine on the migrated database, disposed when the test ends."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def build_current_user_app(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    migrated_database_url: str,
) -> CurrentUserAppFactory:
    """Return a factory giving the built application and a client bound to it, over real Postgres.

    The application is built inside the factory, so the FastAPI error a markerless dependency
    raises belongs to the test that called it rather than to fixture setup.
    """

    def build_application() -> tuple[FastAPI, AbstractAsyncContextManager[httpx.AsyncClient]]:
        """Assemble the app through the public factory and mount the test-only router on it."""
        application = build_server_app(
            test_only_router=build_test_only_router(), database_url=migrated_database_url
        )
        return application, build_api_client(application)

    return build_application


@asynccontextmanager
async def seeded_session(
    engine: AsyncEngine, *, expired: bool = False
) -> AsyncIterator[dict[str, Any]]:
    """Commit one user and one session for it, and delete the user again afterwards.

    The rows are committed rather than held open in a transaction, because the request resolves
    them on its own connection and would never see an uncommitted write.
    """
    email = f"wiring-{uuid.uuid4().hex}@example.test"
    cookie_value = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(days=-1 if expired else 7)
    async with engine.begin() as connection:
        user_id = await connection.scalar(
            INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH}
        )
        session_id = await connection.scalar(
            INSERT_SESSION_SQL,
            {
                "user_id": user_id,
                "token_hash": hashlib.sha256(cookie_value.encode()).hexdigest(),
                "expires_at": expires_at,
            },
        )
    try:
        yield {
            "user_id": user_id,
            "email": email,
            "session_id": session_id,
            "cookie_value": cookie_value,
        }
    finally:
        async with engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"id": user_id})


def build_cookie_header(cookie_value: str | None) -> dict[str, str]:
    """Return the request headers, carrying the session cookie only when there is a value."""
    from app.constants.session import SESSION_COOKIE_NAME  # noqa: PLC0415

    if cookie_value is None:
        return {}
    return {"Cookie": f"{SESSION_COOKIE_NAME}={cookie_value}"}


@pytest.mark.integration
async def test_a_route_depending_on_get_current_user_registers_and_answers(
    build_current_user_app: CurrentUserAppFactory, database_engine: AsyncEngine
) -> None:
    """The application accepts the dependency, documents the route, and serves the identity."""
    application, client_context = build_current_user_app()

    assert CURRENT_USER_PATH in application.openapi()["paths"]

    async with seeded_session(database_engine) as session:
        async with client_context as client:
            response = await client.get(
                CURRENT_USER_PATH, headers=build_cookie_header(session["cookie_value"])
            )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "email": session["email"],
            "user_id": str(session["user_id"]),
            "session_id": str(session["session_id"]),
        }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("cookie_case", "expected_code"),
    [
        ("absent", "AUTH_REQUIRED"),
        ("unknown", "AUTH_REQUIRED"),
        ("malformed", "AUTH_REQUIRED"),
        ("oversized", "AUTH_REQUIRED"),
        ("expired", "AUTH_SESSION_EXPIRED"),
    ],
)
async def test_a_route_depending_on_get_current_user_answers_401_through_the_envelope(
    build_current_user_app: CurrentUserAppFactory,
    database_engine: AsyncEngine,
    cookie_case: str,
    expected_code: str,
) -> None:
    """Every unusable cookie is refused as 401 in the error envelope, never as a 500 or a 422.

    The malformed and oversized cookies are the negative-input cases: a cookie value is client
    input that reaches a SQL lookup, so a route answering anything but a clean 401 for them would
    be either an injection surface or a crash an anonymous caller could provoke at will.
    """
    application, client_context = build_current_user_app()

    assert CURRENT_USER_PATH in application.openapi()["paths"]

    async with seeded_session(database_engine, expired=cookie_case == "expired") as session:
        cookie_values: dict[str, str | None] = {
            "absent": None,
            "unknown": uuid.uuid4().hex,
            "malformed": MALFORMED_COOKIE_VALUE,
            "oversized": OVERSIZED_COOKIE_VALUE,
            "expired": session["cookie_value"],
        }
        async with client_context as client:
            response = await client.get(
                CURRENT_USER_PATH, headers=build_cookie_header(cookie_values[cookie_case])
            )

        assert response.status_code == 401, response.text
        assert response.json()["code"] == expected_code


@pytest.mark.integration
@pytest.mark.parametrize("cookie_case", ["live", "absent", "expired"])
async def test_a_route_depending_on_resolve_current_user_registers_and_answers(
    build_current_user_app: CurrentUserAppFactory, database_engine: AsyncEngine, cookie_case: str
) -> None:
    """The logout resolver is usable as a dependency and answers 200 whether or not it resolves."""
    application, client_context = build_current_user_app()

    assert RESOLVED_USER_PATH in application.openapi()["paths"]

    async with seeded_session(database_engine, expired=cookie_case == "expired") as session:
        cookie_value = None if cookie_case == "absent" else session["cookie_value"]
        async with client_context as client:
            response = await client.get(
                RESOLVED_USER_PATH, headers=build_cookie_header(cookie_value)
            )

        assert response.status_code == 200, response.text
        if cookie_case == "live":
            assert response.json() == {
                "email": session["email"],
                "user_id": str(session["user_id"]),
                "session_id": str(session["session_id"]),
            }
        else:
            assert response.json() == {"email": None, "user_id": None, "session_id": None}
