"""Integration fixtures: point the app at the real Postgres named by TEST_DATABASE_URL.

Overrides the shared `database_url` fixture. When TEST_DATABASE_URL is unset the test is skipped
with a reason that names the variable, because an integration test without a real database has
nothing to assert; CI's integration job always sets it (IAN-124).
"""

import os

import pytest


@pytest.fixture
def database_url() -> str:
    """Return TEST_DATABASE_URL, or skip when no real Postgres is configured."""
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("IAN-124: TEST_DATABASE_URL is unset; integration tests need a real Postgres")
    return test_database_url
