"""B-1 integration test: readiness answers 200 against a real Postgres.

The database comes from TEST_DATABASE_URL through the integration `database_url` fixture; the
test is skipped with a reason when that variable is unset.
"""

import httpx
import pytest


@pytest.mark.integration
async def test_b1_readiness_answers_200_connected_when_postgres_answers(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: GET /health/ready answers 200 with db connected when Postgres answers."""
    response = await api_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected"}
