"""Integration fixtures: point the app at the real Postgres named by TEST_DATABASE_URL.

Overrides the shared `database_url` fixture. When TEST_DATABASE_URL is unset the test is skipped
with a reason that names the variable, because an integration test without a real database has
nothing to assert; CI's integration job always sets it (IAN-124).

The database is migrated once per session before any test reads it, through the same
`alembic upgrade head` that the compose `migrate` service and the end-to-end suite run, so the
schema an integration test sees is the one a deployed process would see rather than one the test
built for itself.

Before any integration test runs, the suite refuses a database that another client is connected
to (IAN-340). Several revision tests downgrade and re-upgrade the schema, and doing that under a
running server invalidates the prepared statements its connection pool holds: the next request on
each pooled connection answers 500 with "cached plan must not change result type", and the one
after it succeeds. Pointed at the compose stack's own `app` database, that made the pre-push
Playwright step fail on the first push and pass on the second. The suite needs a database of its
own, such as `app_test`, which the refusal message says how to create.
"""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = SERVER_ROOT / "alembic.ini"
MIGRATIONS_PATH = SERVER_ROOT / "migrations"

# Every other client session on the current database: a server's pool, another test run, a psql.
# pg_isready is left out: CI's Postgres service health check connects to the same database every
# few seconds under that application name, and a probe that lands on the count is not a server.
OTHER_CLIENTS_SQL = text(
    "SELECT application_name FROM pg_stat_activity WHERE datname = current_database() "
    "AND pid <> pg_backend_pid() AND backend_type = 'client backend' "
    "AND application_name <> 'pg_isready'"
)
# Bounds the guard's one connection, so a host that never answers cannot hang the run.
GUARD_CONNECT_TIMEOUT_SECONDS = 5.0

AlembicConfigFactory = Callable[[str], Config]


async def list_other_database_clients(database_url: str) -> list[str]:
    """Return the application name of every other client session on the database the URL names."""
    engine = create_async_engine(
        database_url, connect_args={"timeout": GUARD_CONNECT_TIMEOUT_SECONDS}
    )
    try:
        async with engine.connect() as connection:
            return list((await connection.scalars(OTHER_CLIENTS_SQL)).all())
    finally:
        await engine.dispose()


def refuse_shared_test_database(database_url: str) -> None:
    """Fail the run when another client holds the database the suite is about to migrate.

    An unreachable database is left to the tests themselves, which report it as they always have.
    """
    try:
        other_client_count = len(asyncio.run(list_other_database_clients(database_url)))
    except (OSError, SQLAlchemyError):
        return
    if other_client_count == 0:
        return
    database_name = make_url(database_url).database
    pytest.fail(
        f'IAN-340: {other_client_count} other client(s) are connected to "{database_name}", '
        "and the integration suite downgrades and re-upgrades its schema, which breaks the "
        "prepared statements of any server using it. Point TEST_DATABASE_URL at a database of "
        "its own, created once with `docker compose exec postgres createdb -U app app_test`.",
        pytrace=False,
    )


@pytest.fixture(scope="session", autouse=True)
def unshared_test_database() -> None:
    """Refuse a shared TEST_DATABASE_URL once, before any integration test touches it."""
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url:
        refuse_shared_test_database(test_database_url)


@pytest.fixture(scope="session")
def alembic_config_factory() -> AlembicConfigFactory:
    """Return a factory building the Alembic config the migration commands run under.

    Both paths are absolute, because pytest's working directory is not guaranteed to be the
    server root and a relative `script_location` would resolve against whatever it happens to be.
    """

    def build_alembic_config(database_url: str) -> Config:
        """Point Alembic at the server tree and the integration database."""
        config = Config(str(ALEMBIC_CONFIG_PATH))
        # Escape percent signs so ConfigParser interpolation preserves the original values.
        config.set_main_option("script_location", str(MIGRATIONS_PATH).replace("%", "%%"))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        return config

    return build_alembic_config


@pytest.fixture(scope="session")
def migrated_database_url(alembic_config_factory: AlembicConfigFactory) -> str:
    """Upgrade the real Postgres to head once per session and return its URL, or skip.

    The upgrade is attempted only when the migration tree is on disk. Alembic raises for a missing
    `script_location` before it looks at the database at all, and a fixture that raised there would
    turn every integration test into a setup error naming Alembic rather than the schema the test
    was about. The tests that need the schema assert its presence themselves.
    """
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("IAN-124: TEST_DATABASE_URL is unset; integration tests need a real Postgres")
    if (
        ALEMBIC_CONFIG_PATH.is_file()
        and (MIGRATIONS_PATH / "env.py").is_file()
        and list((MIGRATIONS_PATH / "versions").glob("*.py"))
    ):
        command.upgrade(alembic_config_factory(test_database_url), "head")
    return test_database_url


@pytest.fixture
def database_url(migrated_database_url: str) -> str:
    """Return the migrated TEST_DATABASE_URL, or skip when no real Postgres is configured."""
    return migrated_database_url
