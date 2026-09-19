"""B-1 unit tests for the health router with Postgres unreachable.

The shared `database_url` fixture points DATABASE_URL at a closed local port, so liveness must
answer without any dependency and readiness must report the database as disconnected with 503.
"""

import httpx


async def test_b1_liveness_answers_200_ok_while_postgres_is_unreachable(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: GET /health answers 200 {"status": "ok"} without touching a dependency."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_b1_readiness_answers_503_degraded_when_postgres_is_unreachable(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: GET /health/ready answers 503 with db disconnected when the engine cannot connect."""
    response = await api_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "disconnected"}


async def test_b1_liveness_still_answers_200_after_a_failed_readiness_probe(
    api_client: httpx.AsyncClient,
) -> None:
    """B-1: a failed readiness connect leaves liveness untouched on the next request."""
    readiness_response = await api_client.get("/health/ready")
    liveness_response = await api_client.get("/health")

    assert readiness_response.status_code == 503
    assert liveness_response.status_code == 200
    assert liveness_response.json() == {"status": "ok"}
