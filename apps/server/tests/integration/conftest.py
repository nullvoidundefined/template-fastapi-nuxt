"""Integration fixtures: point the app at the real Postgres named by TEST_DATABASE_URL.

Overrides the shared `database_url` fixture. When TEST_DATABASE_URL is unset the test is skipped
with a reason that names the variable, because an integration test without a real database has
nothing to assert; CI's integration job always sets it (IAN-124).

The database is migrated once per session before any test reads it, through the same
`alembic upgrade head` that the compose `migrate` service and the end-to-end suite run, so the
schema an integration test sees is the one a deployed process would see rather than one the test
built for itself.
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

SERVER_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = SERVER_ROOT / "alembic.ini"
MIGRATIONS_PATH = SERVER_ROOT / "migrations"

AlembicConfigFactory = Callable[[str], Config]


@pytest.fixture(scope="session")
def alembic_config_factory() -> AlembicConfigFactory:
    """Return a factory building the Alembic config the migration commands run under.

    Both paths are absolute, because pytest's working directory is not guaranteed to be the
    server root and a relative `script_location` would resolve against whatever it happens to be.
    """

    def build_alembic_config(database_url: str) -> Config:
        """Point Alembic at the server tree and the integration database."""
        config = Config(str(ALEMBIC_CONFIG_PATH))
        config.set_main_option("script_location", str(MIGRATIONS_PATH))
        config.set_main_option("sqlalchemy.url", database_url)
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
