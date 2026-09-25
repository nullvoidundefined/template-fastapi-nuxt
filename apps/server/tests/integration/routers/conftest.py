"""Fixtures for the auth and admin endpoints: a reachable Postgres, HTTPS browsers, seeded rows.

These tests deliberately do not use the shared `api_client` and `build_server_app` fixtures, and
the reason matters more than it sounds. Both point `DATABASE_URL` and `REDIS_URL` at a closed
local port, and both speak plain HTTP. Either one alone would let a test here lie. Without a
reachable Postgres every one of these endpoints answers 503 rather than the behavior under test.
Over plain HTTP a `Secure` cookie is never stored or replayed by the client, so a test that means
to prove a cookie stopped working could pass having never sent the cookie at all: the session
would look revoked when in truth the request was anonymous. The base URL is therefore `https://`,
the database is the migrated `TEST_DATABASE_URL`, and every test that proves a session was revoked
first proves that the same cookie authenticated a moment earlier.

The application is always built through the public `create_app()`, so what these tests drive is
the assembly uvicorn runs, middleware chain and exception handlers included.

The helpers are bundled behind `auth_db` and `cookies` rather than offered one fixture each,
because a test function's parameters are its fixtures and ruff's `PLR0913` bounds how many a
function may take; a test that needed six helpers would otherwise have to lose an assertion to a
lint rule.
"""

import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.constants.session import SESSION_COOKIE_NAME, SESSION_TTL
from app.core.security import hash_password

# HTTPS on purpose: an HTTP client stores and replays a `Secure` cookie only for a secure origin,
# and half the assertions in this directory depend on the cookie coming back.
AUTH_BASE_URL = "https://testserver"
# The CSRF guard refuses every unsafe method without it, so it is a default header on the client
# rather than something each POST and PATCH has to remember.
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CLIENT_ADDRESS = "203.0.113.42"
CLIENT_PORT = 54321
CORS_ORIGIN = "https://client.example.test"
# Port 1 is closed, so the rate limiter takes its in-process fallback deterministically and each
# test counts from zero in the application instance it built for itself.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
# A Redis database of its own for the tests that run under `production`, where Redis is mandatory
# and the auth paths fail closed without it. Distinct from the database the rate-limit integration
# tests flush, so neither suite can empty the other's counters.
AUTH_REDIS_DATABASE = 14

INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_SESSION_SQL = text(
    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
    "VALUES (:user_id, :token_hash, :expires_at) RETURNING id"
)
SELECT_USERS_SQL = text(
    "SELECT id, email, password_hash, created_at FROM users WHERE lower(email) = :email"
)
ROLE_COLUMN_EXISTS_SQL = text(
    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
    "WHERE table_name = 'users' AND column_name = 'role')"
)
PROMOTE_TO_ADMIN_SQL = text("UPDATE users SET role = 'admin' WHERE id = :user_id")
SELECT_SESSIONS_SQL = text(
    "SELECT id, user_id, token_hash, expires_at, created_at FROM user_sessions "
    "WHERE user_id = :user_id ORDER BY created_at"
)
# Every address a test creates carries that test's own prefix, so the teardown removes exactly
# what the test made and nothing a parallel worker or an earlier run left behind. The comparison
# is folded because registration stores the address lowercased and some tests submit mixed case.
DELETE_USERS_BY_PREFIX_SQL = text("DELETE FROM users WHERE lower(email) LIKE :prefix")

AuthAppFactory = Callable[..., FastAPI]
EmailFactory = Callable[..., str]


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415

    get_settings.cache_clear()


class AuthDatabase:
    """Seeds and reads the auth tables on a connection no request ever used.

    A test's own engine rather than the application's, so a row that was never committed cannot be
    read back as though it had been, and so a row can be inspected while a request still holds its
    transaction open.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        """Record the engine every statement below runs on."""
        self.engine = engine

    async def seed_user(self, email: str, password: str) -> uuid.UUID:
        """Commit one user carrying a real bcrypt hash of the password, and return its id.

        Seeded rather than registered through the API, so a test about logging in fails for the
        login endpoint's own reasons rather than for the registration endpoint's.
        """
        password_hash = await hash_password(password)
        async with self.engine.begin() as connection:
            user_id = await connection.scalar(
                INSERT_USER_SQL, {"email": email, "password_hash": password_hash}
            )
        return uuid.UUID(str(user_id))

    async def seed_session(
        self, user_id: uuid.UUID, raw_token: str, expired: bool = False
    ) -> uuid.UUID:
        """Commit one session storing only the SHA-256 of the raw token, and return its id."""
        expires_at = datetime.now(UTC) + (timedelta(days=-1) if expired else SESSION_TTL)
        async with self.engine.begin() as connection:
            session_id = await connection.scalar(
                INSERT_SESSION_SQL,
                {
                    "user_id": user_id,
                    "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
                    "expires_at": expires_at,
                },
            )
        return uuid.UUID(str(session_id))

    async def promote_to_admin(self, user_id: uuid.UUID) -> None:
        """Commit the admin role onto an existing user, which only an operator can do.

        The column is checked first, so a schema without roles fails as an assertion naming the
        missing column rather than as a driver error from inside a fixture helper.
        """
        async with self.engine.begin() as connection:
            assert await connection.scalar(ROLE_COLUMN_EXISTS_SQL), "users has no role column"
            await connection.execute(PROMOTE_TO_ADMIN_SQL, {"user_id": user_id})

    async def read_users(self, email: str) -> list[Row[Any]]:
        """Return every user row whose folded address matches, oldest first.

        A list rather than one row, so a test can assert that a duplicate registration created no
        second account instead of raising where it meant to assert.
        """
        async with self.engine.connect() as connection:
            result = await connection.execute(SELECT_USERS_SQL, {"email": email.strip().lower()})
            return list(result)

    async def read_sessions(self, user_id: uuid.UUID) -> list[Row[Any]]:
        """Return every session row this user owns, oldest first."""
        async with self.engine.connect() as connection:
            result = await connection.execute(SELECT_SESSIONS_SQL, {"user_id": user_id})
            return list(result)


class CookieTools:
    """Reads what a browser would enforce, and replays a token the client's jar no longer holds."""

    @staticmethod
    def attributes(response: httpx.Response, name: str = SESSION_COOKIE_NAME) -> dict[str, str]:
        """Return `{"value": ..., <attribute>: ...}` for the named cookie, or {} when unset.

        The header is parsed rather than the client's cookie jar read, because the jar keeps only
        the attributes it chose to honor: a cleared cookie is simply absent from it, and a missing
        `HttpOnly` leaves no trace there at all. The attributes are what a browser enforces, so
        the attributes are what these tests assert.
        """
        for header in response.headers.get_list("set-cookie"):
            assignment, _, remainder = header.partition(";")
            cookie_name, _, cookie_value = assignment.partition("=")
            if cookie_name.strip() != name:
                continue
            attributes = {"value": cookie_value.strip()}
            for part in remainder.split(";"):
                if not part.strip():
                    continue
                attribute_name, _, attribute_value = part.partition("=")
                attributes[attribute_name.strip().lower()] = attribute_value.strip()
            return attributes
        return {}

    @staticmethod
    def header(raw_token: str) -> dict[str, str]:
        """Return request headers carrying this raw session token.

        Used wherever a test replays a token the client's own jar no longer holds, such as after a
        logout cleared it, so the assertion is about the server having revoked the session rather
        than about the client having forgotten it.
        """
        return {"Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}


@pytest.fixture
def build_auth_app(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> Iterator[AuthAppFactory]:
    """Return a factory building the real application against the migrated Postgres.

    `tls_to_postgres` exists for the tests that run under `production`. A deployed environment
    connects to Postgres with a verified certificate and the local Postgres these tests use has
    none, so such a test empties `app.db.engine.TLS_ENVIRONMENTS` for its own application only.
    What it asserts is the production branch of the cookie policy, not the transport to the
    database, and leaving TLS on would make the assertion impossible to write rather than stronger.
    """

    def build_application(
        environment: str = "test",
        redis_url: str = UNREACHABLE_REDIS_URL,
        tls_to_postgres: bool = True,
    ) -> FastAPI:
        """Patch the environment this application reads and assemble it through create_app()."""
        monkeypatch.setenv("DATABASE_URL", migrated_database_url)
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("REDIS_URL", redis_url)
        monkeypatch.setenv("CORS_ORIGIN", CORS_ORIGIN)
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", CLIENT_ADDRESS)
        if not tls_to_postgres:
            monkeypatch.setattr("app.db.engine.TLS_ENVIRONMENTS", frozenset())
        from app.main import create_app  # noqa: PLC0415

        clear_settings_cache()
        return create_app()

    yield build_application
    clear_settings_cache()


@pytest.fixture
def open_auth_browsers() -> Callable[..., AbstractAsyncContextManager[list[httpx.AsyncClient]]]:
    """Return a context manager opening one or more browsers on one running application.

    Browsers rather than clients, because each has its own cookie jar and that is exactly what a
    second browser of the same user is. The lifespan runs once around all of them: running it per
    client would build a second engine, bind it to the same application, and dispose it under the
    first client's feet when the inner block exited.

    `raise_app_exceptions=False` so an exception a route raises comes back as the response the
    registered handler produced rather than being re-raised into the test.
    """

    @asynccontextmanager
    async def open_browsers(
        application: FastAPI, count: int = 1, client_address: str = CLIENT_ADDRESS
    ) -> AsyncIterator[list[httpx.AsyncClient]]:
        """Yield `count` independent clients, all bound to one application under its lifespan."""
        transport = httpx.ASGITransport(
            app=application, client=(client_address, CLIENT_PORT), raise_app_exceptions=False
        )
        async with application.router.lifespan_context(application), AsyncExitStack() as stack:
            yield [
                await stack.enter_async_context(
                    httpx.AsyncClient(
                        transport=transport,
                        base_url=AUTH_BASE_URL,
                        headers=dict(CSRF_HEADERS),
                    )
                )
                for _ in range(count)
            ]

    return open_browsers


@pytest_asyncio.fixture
async def auth_client(
    build_auth_app: AuthAppFactory,
    open_auth_browsers: Callable[..., AbstractAsyncContextManager[list[httpx.AsyncClient]]],
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield the common case: one browser talking to one application over HTTPS."""
    async with open_auth_browsers(build_auth_app()) as browsers:
        yield browsers[0]


@pytest_asyncio.fixture
async def auth_redis_url() -> str:
    """Return a flushed Redis database URL for a production run, or skip naming the variable.

    Production makes Redis mandatory and the four auth paths fail closed when it does not answer,
    so a production test needs a real one or it would be asserting on a 503.
    """
    test_redis_url = os.environ.get("TEST_REDIS_URL")
    if not test_redis_url:
        pytest.skip("IAN-171: TEST_REDIS_URL is unset; the production cookie test needs a Redis")
    parts = urlsplit(test_redis_url)
    auth_url = urlunsplit(
        (parts.scheme, parts.netloc, f"/{AUTH_REDIS_DATABASE}", parts.query, parts.fragment)
    )
    redis_client: Redis = Redis.from_url(auth_url)
    try:
        await redis_client.flushdb()
    except (OSError, RedisError):
        pytest.skip("IAN-171: the Redis at TEST_REDIS_URL did not answer; this test needs it")
    finally:
        await redis_client.aclose()
    return auth_url


@pytest_asyncio.fixture
async def auth_db(migrated_database_url: str) -> AsyncIterator[AuthDatabase]:
    """Yield the seeding and reading helpers on an engine of the test's own."""
    engine = create_async_engine(migrated_database_url)
    try:
        yield AuthDatabase(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def auth_emails(auth_db: AuthDatabase) -> AsyncIterator[EmailFactory]:
    """Yield a factory for this test's addresses and delete every account it made afterwards."""
    prefix = f"authtest-{uuid.uuid4().hex}"

    def make_email(label: str = "user") -> str:
        """Return a unique address for this test, carrying the prefix the teardown deletes by."""
        return f"{prefix}-{label}@example.test"

    try:
        yield make_email
    finally:
        async with auth_db.engine.begin() as connection:
            await connection.execute(DELETE_USERS_BY_PREFIX_SQL, {"prefix": f"{prefix}%"})


@pytest.fixture
def cookies() -> CookieTools:
    """Return the cookie helpers: the attributes a browser enforces, and a replay header."""
    return CookieTools()
