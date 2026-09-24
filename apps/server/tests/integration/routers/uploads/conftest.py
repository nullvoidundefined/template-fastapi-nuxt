"""Fixtures for `POST /v1/uploads`: a signed-in browser, and R2 replaced at the SDK boundary.

The route needs a real session, so the application is built through `create_app()` against the
migrated `TEST_DATABASE_URL` and a user and session are committed directly, the session storing
only the SHA-256 of the raw token as the real one does. The base URL is HTTPS so the client
replays the `Secure` cookie, as in the auth suite.

R2 is replaced one layer below the application's own client: `app.state.storage_client` is a real
`R2Client` whose boto3 client is a recorder. The service, the key builder, and the telemetry
wrapper therefore all run, and the recorder shows whether anything reached the provider at all,
which is what B-29's "before any R2 call" is about.
"""

import hashlib
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.constants.session import SESSION_COOKIE_NAME

UPLOADS_BASE_URL = "https://testserver"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
BUCKET = "template-uploads-test"
PRESIGNED_URL = "https://r2.example.test/presigned-put"

INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"
)
INSERT_SESSION_SQL = text(
    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
    "VALUES (:user_id, :token_hash, :expires_at)"
)
DELETE_USER_SQL = text("DELETE FROM users WHERE id = :user_id")


@dataclass
class RecordingS3Client:
    """Stands in for boto3's S3 client, recording every presign it is asked for."""

    presign_calls: list[dict[str, object]] = field(default_factory=list)

    def generate_presigned_url(self, **kwargs: object) -> str:
        """Record the request and answer with a fixed URL."""
        self.presign_calls.append(kwargs)
        return PRESIGNED_URL


@dataclass
class UploadsHarness:
    """Everything a test needs: the app, its recorder, and the signed-in user's id."""

    application: FastAPI
    s3_client: RecordingS3Client
    user_id: uuid.UUID
    raw_token: str


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next create_app() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415

    get_settings.cache_clear()


@pytest.fixture
def uploads_application(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> Iterator[FastAPI]:
    """Build the application through create_app() against the migrated Postgres."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
    from app.main import create_app  # noqa: PLC0415

    clear_settings_cache()
    yield create_app()
    clear_settings_cache()


@pytest_asyncio.fixture
async def uploads_harness(
    uploads_application: FastAPI, migrated_database_url: str
) -> AsyncIterator[UploadsHarness]:
    """Commit a user with a live session, install the recording R2 client, and clean up after."""
    from app.clients.r2 import R2Client  # noqa: PLC0415

    s3_client = RecordingS3Client()
    uploads_application.state.storage_client = R2Client(s3_client, BUCKET)
    raw_token = secrets.token_hex(32)
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.begin() as connection:
            user_id = await connection.scalar(
                INSERT_USER_SQL,
                {"email": f"uploads-{uuid.uuid4().hex}@example.test", "password_hash": "x"},
            )
            await connection.execute(
                INSERT_SESSION_SQL,
                {
                    "user_id": user_id,
                    "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
                    "expires_at": datetime.now(UTC) + timedelta(days=1),
                },
            )
        yield UploadsHarness(uploads_application, s3_client, uuid.UUID(str(user_id)), raw_token)
        async with engine.begin() as connection:
            await connection.execute(DELETE_USER_SQL, {"user_id": user_id})
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def uploads_client(uploads_harness: UploadsHarness) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client for the harness's application, carrying the session cookie."""
    application = uploads_harness.application
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=transport,
            base_url=UPLOADS_BASE_URL,
            headers={
                **CSRF_HEADERS,
                "Cookie": f"{SESSION_COOKIE_NAME}={uploads_harness.raw_token}",
            },
        ) as client,
    ):
        yield client
