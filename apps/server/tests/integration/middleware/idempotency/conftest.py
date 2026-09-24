"""Fixtures for the idempotency middleware: a test-only router, seeded sessions, the claim table.

The spec's slice plan exercises the idempotency criteria through a test-only router mounted by the
test application factory, because the first real replayable authenticated `POST` arrives in slice
06. The application is still built through the public `create_app()`, so every request passes the
real middleware chain in its real order against the migrated Postgres.

The router's handlers report to a `HandlerProbe`: how many times they ran, and, for the concurrency
tests, a pair of events per call so a test can hold one handler open while it sends another
request. That is what makes the overlap real rather than two sequential calls: the first request
has claimed its key in Postgres and is still inside its handler when the second arrives.

Every row a test creates hangs off a user carrying the test's own address prefix, and deleting
those users afterwards removes their claims through `ON DELETE CASCADE`.
"""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

ECHO_PATH = "/test-only/idempotent/echo"
OTHER_PATH = "/test-only/idempotent/other"
FLAKY_PATH = "/test-only/idempotent/flaky"
UNAVAILABLE_PATH = "/test-only/idempotent/unavailable"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
PASSWORD_HASH = "-".join(("test", "hash"))
HOLD_TIMEOUT_SECONDS = 10

TABLE_EXISTS_SQL = text("SELECT to_regclass('request_idempotency_keys') IS NOT NULL")
INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_SESSION_SQL = text(
    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
    "VALUES (:user_id, :token_hash, :expires_at)"
)
DELETE_USERS_BY_PREFIX_SQL = text("DELETE FROM users WHERE email LIKE :prefix")
READ_CLAIM_SQL = text(
    "SELECT key, user_id, request_method, request_path, request_body_hash, state::text AS state, "
    "locked_until, claim_token, status_code, response_body, created_at, "
    "locked_until > now() AS is_lease_live "
    "FROM request_idempotency_keys WHERE key = :key AND user_id = :user_id"
)
INSERT_CLAIM_SQL = text(
    "INSERT INTO request_idempotency_keys (key, user_id, request_method, request_path, "
    "request_body_hash, state, locked_until, claim_token) "
    "VALUES (:key, :user_id, :request_method, :request_path, :request_body_hash, 'in_progress', "
    "now() + make_interval(secs => :lease_seconds), :claim_token)"
)
EXPIRE_LEASE_SQL = text(
    "UPDATE request_idempotency_keys SET locked_until = now() - interval '1 second' "
    "WHERE key = :key AND user_id = :user_id"
)
AGE_CLAIM_SQL = text(
    "UPDATE request_idempotency_keys SET created_at = now() - interval '25 hours' "
    "WHERE key = :key AND user_id = :user_id"
)

IdempotencyAppFactory = Callable[[], tuple[FastAPI, AbstractAsyncContextManager[httpx.AsyncClient]]]


def encode_body(payload: dict[str, Any]) -> bytes:
    """Return the exact bytes a request sends, so a test can hash what the middleware hashes."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def hash_body(body: bytes) -> str:
    """Return the SHA-256 the spec binds a key to, as lowercase hex."""
    return hashlib.sha256(body).hexdigest()


@dataclass
class HandlerProbe:
    """Counts handler runs and lets a test hold chosen calls open until it releases them.

    `held_calls` names the call numbers, counted from one, that wait inside the handler. For each
    one, `entered[n]` is set once the handler is running and `release[n]` lets it finish.
    `failing_calls` names the calls that raise after being released.
    """

    calls: int = 0
    held_calls: set[int] = field(default_factory=set)
    failing_calls: set[int] = field(default_factory=set)
    entered: dict[int, asyncio.Event] = field(default_factory=dict)
    release: dict[int, asyncio.Event] = field(default_factory=dict)

    def hold(self, call_number: int) -> None:
        """Make the given call wait inside the handler until the test releases it."""
        self.held_calls.add(call_number)
        self.entered[call_number] = asyncio.Event()
        self.release[call_number] = asyncio.Event()

    async def wait_until_entered(self, call_number: int) -> None:
        """Return once the given call is running inside the handler."""
        await asyncio.wait_for(self.entered[call_number].wait(), HOLD_TIMEOUT_SECONDS)

    async def run_call(self) -> int:
        """Count one run, wait if this call is held, and raise if it is meant to fail."""
        self.calls += 1
        call_number = self.calls
        if call_number in self.held_calls:
            self.entered[call_number].set()
            await asyncio.wait_for(self.release[call_number].wait(), HOLD_TIMEOUT_SECONDS)
        if call_number in self.failing_calls:
            raise RuntimeError("Test-only handler failure")
        return call_number


def build_test_only_router(probe: HandlerProbe) -> APIRouter:
    """Return the routes the idempotency criteria are driven through."""
    router = APIRouter()

    async def echo(request: Request) -> JSONResponse:
        """Answer 201 with the call number and the body, so a replay is recognizable."""
        call_number = await probe.run_call()
        payload = json.loads(await request.body() or b"null")
        return JSONResponse({"data": {"call": call_number, "body": payload}}, status_code=201)

    async def fail_first(request: Request) -> JSONResponse:
        """Raise on the first call and succeed afterwards, like a transient outage."""
        call_number = await probe.run_call()
        if call_number == 1:
            raise RuntimeError("Test-only transient failure")
        return JSONResponse({"data": {"call": call_number}}, status_code=201)

    async def unavailable_first(request: Request) -> JSONResponse:
        """Answer a 503 on the first call and succeed afterwards, without raising."""
        call_number = await probe.run_call()
        if call_number == 1:
            return JSONResponse({"code": "TEST_ONLY_UNAVAILABLE", "error": "down"}, 503)
        return JSONResponse({"data": {"call": call_number}}, status_code=201)

    router.add_api_route(ECHO_PATH, echo, methods=["POST", "PUT"])
    router.add_api_route(OTHER_PATH, echo, methods=["POST"])
    router.add_api_route(FLAKY_PATH, fail_first, methods=["POST"])
    router.add_api_route(UNAVAILABLE_PATH, unavailable_first, methods=["POST"])
    return router


@dataclass
class SignedInUser:
    """A committed user with a live session, and the headers a request of theirs carries."""

    id: uuid.UUID
    headers: dict[str, str]


class IdempotencyDatabase:
    """Seeds users and claims and reads claims back, on an engine no request uses."""

    def __init__(self, engine: AsyncEngine, email_prefix: str) -> None:
        """Record the engine and the address prefix the teardown deletes by."""
        self.engine = engine
        self.email_prefix = email_prefix

    async def assert_table_exists(self) -> None:
        """Fail as an assertion, naming the table, when the revision has not run."""
        async with self.engine.connect() as connection:
            assert await connection.scalar(TABLE_EXISTS_SQL), "request_idempotency_keys is missing"

    async def sign_in_user(self, label: str = "user") -> SignedInUser:
        """Commit a user and a live session, and return the headers that authenticate as them."""
        from app.constants.session import SESSION_COOKIE_NAME  # noqa: PLC0415

        raw_token = uuid.uuid4().hex
        async with self.engine.begin() as connection:
            user_id = await connection.scalar(
                INSERT_USER_SQL,
                {
                    "email": f"{self.email_prefix}-{label}@example.test",
                    "password_hash": PASSWORD_HASH,
                },
            )
            await connection.execute(
                INSERT_SESSION_SQL,
                {
                    "user_id": user_id,
                    "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
                    "expires_at": datetime.now(UTC) + timedelta(days=1),
                },
            )
        headers = {**CSRF_HEADERS, "Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}
        return SignedInUser(id=uuid.UUID(str(user_id)), headers=headers)

    async def read_claim(self, key: str, user_id: uuid.UUID) -> Row[Any] | None:
        """Return the claim row for this key and user, or None when there is none."""
        await self.assert_table_exists()
        async with self.engine.connect() as connection:
            result = await connection.execute(READ_CLAIM_SQL, {"key": key, "user_id": user_id})
            return result.one_or_none()

    async def seed_claim(
        self, key: str, user_id: uuid.UUID, path: str, body: bytes, *, lease_seconds: float
    ) -> uuid.UUID:
        """Commit an in-progress POST claim as another process left it; return its claim token.

        A negative `lease_seconds` leaves the lease already expired, as a crashed holder would.
        """
        await self.assert_table_exists()
        claim_token = uuid.uuid4()
        async with self.engine.begin() as connection:
            await connection.execute(
                INSERT_CLAIM_SQL,
                {
                    "key": key,
                    "user_id": user_id,
                    "request_method": "POST",
                    "request_path": path,
                    "request_body_hash": hash_body(body),
                    "lease_seconds": float(lease_seconds),
                    "claim_token": claim_token,
                },
            )
        return claim_token

    async def expire_lease(self, key: str, user_id: uuid.UUID) -> None:
        """Move the claim's lease into the past, as sixty seconds passing would."""
        await self.assert_table_exists()
        async with self.engine.begin() as connection:
            await connection.execute(EXPIRE_LEASE_SQL, {"key": key, "user_id": user_id})

    async def age_past_replay_window(self, key: str, user_id: uuid.UUID) -> None:
        """Move the claim's creation more than twenty-four hours into the past."""
        await self.assert_table_exists()
        async with self.engine.begin() as connection:
            await connection.execute(AGE_CLAIM_SQL, {"key": key, "user_id": user_id})


@pytest.fixture
def handler_probe() -> HandlerProbe:
    """Return a fresh probe for this test's handlers."""
    return HandlerProbe()


@pytest_asyncio.fixture
async def idempotency_db(migrated_database_url: str) -> AsyncIterator[IdempotencyDatabase]:
    """Yield the seeding helpers and delete every user this test made, with their claims."""
    engine = create_async_engine(migrated_database_url)
    prefix = f"idempotency-{uuid.uuid4().hex}"
    try:
        yield IdempotencyDatabase(engine, prefix)
    finally:
        async with engine.begin() as connection:
            await connection.execute(DELETE_USERS_BY_PREFIX_SQL, {"prefix": f"{prefix}%"})
        await engine.dispose()


@pytest.fixture
def idempotency_app(
    build_server_app: Callable[..., FastAPI],
    build_api_client: Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]],
    migrated_database_url: str,
    handler_probe: HandlerProbe,
) -> AbstractAsyncContextManager[httpx.AsyncClient]:
    """Return a client context for the real application with the test-only router mounted."""
    application = build_server_app(
        test_only_router=build_test_only_router(handler_probe),
        database_url=migrated_database_url,
    )
    return build_api_client(application)


def build_request_headers(user: SignedInUser, key: str | None) -> dict[str, str]:
    """Return the user's headers, with the Idempotency-Key when one is given."""
    headers = {**user.headers, "Content-Type": "application/json"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def build_unique_key() -> str:
    """Return a key no other test has used."""
    return f"key-{uuid.uuid4().hex}"
