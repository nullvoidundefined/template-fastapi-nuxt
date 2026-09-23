"""Exercise auth persistence, dependency resolution, and serialization against real Postgres.

The proposed repository contract uses connection-first functions: get_user_by_email,
lock_user_for_update, create_session, and touch_session. Resolvers accept request and connection
and return a typed object exposing user and session_id, or None for the non-raising resolver.
All absent production imports occur in test bodies so RED is never a fixture setup error.
"""

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from starlette.requests import Request

AlembicConfigFactory = Callable[[str], Config]
FIRST_REVISION = "20260923_0001"


@asynccontextmanager
async def open_database(config_factory: AlembicConfigFactory) -> AsyncIterator[AsyncEngine]:
    """Probe Postgres before migrating, skipping unavailable services only in the test body."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("IAN-315: TEST_DATABASE_URL is unset; auth tests need Postgres")
    engine = create_async_engine(database_url)
    try:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError) as error:
            pytest.skip(f"IAN-315: TEST_DATABASE_URL is unreachable ({type(error).__name__})")
        await asyncio.to_thread(command.upgrade, config_factory(database_url), "head")
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def seeded_user(engine: AsyncEngine) -> AsyncIterator[tuple[uuid.UUID, str]]:
    """Commit an isolated user for concurrent transactions and remove it after the test."""
    email = f"session-{uuid.uuid4().hex}@example.test"
    async with engine.begin() as connection:
        user_id = await connection.scalar(
            text("INSERT INTO users (email, password_hash) VALUES (:email, :hash) RETURNING id"),
            {"email": email, "hash": "-".join(("test", "hash"))},
        )
    try:
        yield user_id, email
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def seed_session(
    connection: AsyncConnection, user_id: uuid.UUID, *, expired: bool = False
) -> tuple[uuid.UUID, str]:
    """Insert a session independently of repositories to avoid circular test assertions."""
    raw_token = uuid.uuid4().hex
    session_id = await connection.scalar(
        text(
            "INSERT INTO user_sessions (user_id, token_hash, expires_at, last_seen_at) "
            "VALUES (:user_id, :hash, :expiry, now() - interval '6 minutes') RETURNING id"
        ),
        {
            "user_id": user_id,
            "hash": hashlib.sha256(raw_token.encode()).hexdigest(),
            "expiry": datetime.now(UTC) + timedelta(days=-1 if expired else 1),
        },
    )
    return session_id, raw_token


def build_request(raw_token: str | None, cookie_name: str) -> Request:
    """Construct a real Starlette request with an optional session cookie."""
    headers = [] if raw_token is None else [(b"cookie", f"{cookie_name}={raw_token}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.integration
async def test_session_revision_is_reversible(alembic_config_factory: AlembicConfigFactory) -> None:
    """Downgrading only the session revision preserves users and upgrading restores sessions."""
    async with open_database(alembic_config_factory) as engine:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('user_sessions') IS NOT NULL"))
        config = alembic_config_factory(os.environ["TEST_DATABASE_URL"])
        try:
            await asyncio.to_thread(command.downgrade, config, FIRST_REVISION)
            async with engine.connect() as connection:
                assert not await connection.scalar(
                    text("SELECT to_regclass('user_sessions') IS NOT NULL")
                )
                assert await connection.scalar(text("SELECT to_regclass('users') IS NOT NULL"))
                assert await connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'set_updated_at')")
                )
        finally:
            await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('user_sessions') IS NOT NULL"))


@pytest.mark.integration
async def test_session_schema_constraints_and_cascade(
    alembic_config_factory: AlembicConfigFactory,
) -> None:
    """The migrated table enforces unique hashes, required columns, indexing, and cascade."""
    from app.db.tables import metadata, user_sessions  # noqa: PLC0415

    assert user_sessions.metadata is metadata
    assert set(user_sessions.c.keys()) == {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "created_at",
        "last_seen_at",
    }
    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, _ = user
        async with engine.begin() as connection:
            session_id, _ = await seed_session(connection, user_id)
            columns = (
                await connection.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'user_sessions'"
                    )
                )
            ).all()
            assert {name for name, nullable in columns if nullable == "NO"} == set(
                user_sessions.c.keys()
            )
            indexes = (
                (
                    await connection.execute(
                        text(
                            "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                            "AND tablename = 'user_sessions'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any("(expires_at)" in definition for definition in indexes)
            constraints = (
                (
                    await connection.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conrelid = 'user_sessions'::regclass"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "PRIMARY KEY (id)" in constraints
            assert "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE" in constraints
            timestamp_columns = (
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'user_sessions' "
                            "AND data_type = 'timestamp with time zone'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert set(timestamp_columns) == {"created_at", "last_seen_at", "expires_at"}
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
                            "SELECT user_id, token_hash, expires_at FROM user_sessions "
                            "WHERE id = :id"
                        ),
                        {"id": session_id},
                    )
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM user_sessions WHERE id = :id"), {"id": session_id}
                )
                == 0
            )


@pytest.mark.integration
@pytest.mark.parametrize("lookup_name", ["get_user_by_email", "lock_user_for_update"])
async def test_email_lookups_trim_and_lowercase(
    alembic_config_factory: AlembicConfigFactory, lookup_name: str
) -> None:
    """Both ordinary and locking lookups find a padded mixed-case address."""
    from app.repositories.users import get_user_by_email, lock_user_for_update  # noqa: PLC0415

    lookup = {"get_user_by_email": get_user_by_email, "lock_user_for_update": lock_user_for_update}[
        lookup_name
    ]
    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, email = user
        async with engine.begin() as connection:
            found = await lookup(connection, f"  {email.upper()}  ")
            assert found is not None
            assert found.id == user_id
            assert await lookup(connection, f"absent-{email}") is None


async def wait_for_blocked_transaction(
    observer: AsyncConnection, blocked_pid: int, holder_pid: int, contender: asyncio.Task[None]
) -> None:
    """Observe PostgreSQL's actual lock graph instead of inferring blocking from elapsed time."""
    try:
        async with asyncio.timeout(5):
            while True:
                blockers = await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": blocked_pid}
                )
                if holder_pid in blockers:
                    assert not contender.done()
                    return
                assert not contender.done(), "The second transaction acquired an unlocked user"
                await asyncio.sleep(0)
    except TimeoutError as error:
        raise AssertionError("Postgres never reported the expected row-lock wait") from error


@pytest.mark.integration
async def test_user_row_lock_serializes_concurrent_transactions(
    alembic_config_factory: AlembicConfigFactory,
) -> None:
    """The second caller waits on the first transaction and sees its committed change."""
    from app.repositories.users import lock_user_for_update  # noqa: PLC0415

    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, email = user
        async with (
            engine.connect() as first,
            engine.connect() as second,
            engine.connect() as observer,
        ):
            holder = await first.begin()
            holder_pid = await first.scalar(text("SELECT pg_backend_pid()"))
            blocked_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            await second.commit()
            locked_user = await lock_user_for_update(first, email)
            assert locked_user.id == user_id
            acquired = asyncio.Event()
            started = asyncio.Event()

            async def lock_second_transaction() -> None:
                """Attempt the same user lock while the first transaction still holds it."""
                async with second.begin():
                    started.set()
                    result = await lock_user_for_update(second, email)
                    acquired.set()
                    assert result.id == user_id
                    assert result.password_hash == "-".join(("updated", "test", "hash"))

            contender = asyncio.create_task(lock_second_transaction())
            try:
                await started.wait()
                await wait_for_blocked_transaction(observer, blocked_pid, holder_pid, contender)
                assert not acquired.is_set()
                await first.execute(
                    text("UPDATE users SET password_hash = :hash WHERE id = :id"),
                    {"hash": "updated-test-hash", "id": user_id},
                )
                await holder.commit()
                try:
                    await asyncio.wait_for(contender, 5)
                except TimeoutError as error:
                    raise AssertionError("The second lock did not resume after commit") from error
                assert acquired.is_set()
            finally:
                if holder.is_active:
                    await holder.rollback()
                contender.cancel()
                await asyncio.gather(contender, return_exceptions=True)


@pytest.mark.integration
async def test_repository_persists_only_the_token_hash(
    alembic_config_factory: AlembicConfigFactory,
) -> None:
    """A generated token is represented only by its SHA-256 in the persisted session."""
    from app.core.security import generate_session_token  # noqa: PLC0415
    from app.repositories.user_sessions import create_session  # noqa: PLC0415

    raw_token, token_hash = generate_session_token()
    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, _ = user
        async with engine.begin() as connection:
            await create_session(
                connection, user_id, token_hash, datetime.now(UTC) + timedelta(days=7)
            )
            rows = (
                (
                    await connection.execute(
                        text("SELECT * FROM user_sessions WHERE user_id = :id"), {"id": user_id}
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 1
            assert rows[0]["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()
            assert raw_token not in {str(value) for value in rows[0].values()}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("absent", "AUTH_REQUIRED"),
        ("unknown", "AUTH_REQUIRED"),
        ("expired", "AUTH_SESSION_EXPIRED"),
        ("live", None),
    ],
)
async def test_current_user_distinguishes_session_states(
    alembic_config_factory: AlembicConfigFactory, state: str, expected_code: str | None
) -> None:
    """Resolve a live session with its identity and preserve distinct authentication errors."""
    from app.constants.session import SESSION_COOKIE_NAME  # noqa: PLC0415
    from app.dependencies.current_user import get_current_user  # noqa: PLC0415

    from app.errors import AppError  # noqa: PLC0415

    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, email = user
        async with engine.begin() as connection:
            session_id, raw_token = await seed_session(
                connection, user_id, expired=state == "expired"
            )
            candidate = None if state == "absent" else raw_token
            if state == "unknown":
                candidate = uuid.uuid4().hex
            request = build_request(candidate, SESSION_COOKIE_NAME)
            if expected_code:
                with pytest.raises(AppError) as captured:
                    await get_current_user(request, connection)
                assert captured.value.code == expected_code
                assert captured.value.status_code == 401
            else:
                result = await get_current_user(request, connection)
                assert result.user.id == user_id
                assert result.user.email == email
                assert result.session_id == session_id
                assert getattr(type(result), "__annotations__", {})


@pytest.mark.integration
@pytest.mark.parametrize("state", ["absent", "unknown", "expired", "live"])
async def test_logout_resolver_never_raises_for_invalid_sessions(
    alembic_config_factory: AlembicConfigFactory, state: str
) -> None:
    """Logout tolerates missing, unknown, and expired tokens and resolves a live session."""
    from app.constants.session import SESSION_COOKIE_NAME  # noqa: PLC0415
    from app.dependencies.current_user import resolve_current_user  # noqa: PLC0415

    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, _ = user
        async with engine.begin() as connection:
            session_id, raw_token = await seed_session(
                connection, user_id, expired=state == "expired"
            )
            candidate = None if state == "absent" else raw_token
            if state == "unknown":
                candidate = uuid.uuid4().hex
            result = await resolve_current_user(
                build_request(candidate, SESSION_COOKIE_NAME), connection
            )
            if state == "live":
                assert result.user.id == user_id
                assert result.session_id == session_id
            else:
                assert result is None


async def read_session_version(
    connection: AsyncConnection, session_id: uuid.UUID
) -> Row[tuple[datetime, str, str]]:
    """Read timestamp and tuple version so a redundant UPDATE cannot hide behind now()."""
    return (
        await connection.execute(
            text("SELECT last_seen_at, xmin::text, ctid::text FROM user_sessions WHERE id = :id"),
            {"id": session_id},
        )
    ).one()


@pytest.mark.integration
async def test_last_seen_changes_only_after_five_minutes(
    alembic_config_factory: AlembicConfigFactory,
) -> None:
    """A stale timestamp advances once while an immediate second request does not write."""
    from app.repositories.user_sessions import touch_session  # noqa: PLC0415

    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, _ = user
        async with engine.begin() as connection:
            session_id, _ = await seed_session(connection, user_id)
            stale = await read_session_version(connection, session_id)
            await touch_session(connection, session_id)
            refreshed = await read_session_version(connection, session_id)
            assert refreshed.last_seen_at > stale.last_seen_at
        async with engine.begin() as connection:
            await touch_session(connection, session_id)
            assert await read_session_version(connection, session_id) == refreshed
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE user_sessions SET last_seen_at = now() - interval '301 seconds' "
                    "WHERE id = :id"
                ),
                {"id": session_id},
            )
        async with engine.begin() as connection:
            old = await read_session_version(connection, session_id)
            await touch_session(connection, session_id)
            assert (
                await read_session_version(connection, session_id)
            ).last_seen_at > old.last_seen_at


@pytest.mark.integration
async def test_simultaneous_last_seen_requests_write_once(
    alembic_config_factory: AlembicConfigFactory,
) -> None:
    """A concurrent updater rechecks the condition after waiting for the winning update."""
    from app.repositories.user_sessions import touch_session  # noqa: PLC0415

    async with open_database(alembic_config_factory) as engine, seeded_user(engine) as user:
        user_id, _ = user
        async with engine.begin() as connection:
            session_id, _ = await seed_session(connection, user_id)
        async with (
            engine.connect() as first,
            engine.connect() as second,
            engine.connect() as observer,
        ):
            holder = await first.begin()
            holder_pid = await first.scalar(text("SELECT pg_backend_pid()"))
            blocked_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            await second.commit()
            await touch_session(first, session_id)
            winner = await read_session_version(first, session_id)

            async def touch_contending_session() -> None:
                """Read the stale committed row while the first update remains uncommitted."""
                async with second.begin():
                    await touch_session(second, session_id)

            contender = asyncio.create_task(touch_contending_session())
            try:
                await wait_for_blocked_transaction(observer, blocked_pid, holder_pid, contender)
                await holder.commit()
                try:
                    await asyncio.wait_for(contender, 5)
                except TimeoutError as error:
                    raise AssertionError(
                        "The session updater did not resume after commit"
                    ) from error
                assert await read_session_version(observer, session_id) == winner
            finally:
                if holder.is_active:
                    await holder.rollback()
                contender.cancel()
                await asyncio.gather(contender, return_exceptions=True)
