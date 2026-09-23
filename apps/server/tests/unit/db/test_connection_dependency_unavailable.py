"""B-9 unit test: a route taking `get_connection` answers 503 when Postgres cannot be reached.

The default `build_server_app` database URL points at a closed local port, so the connect the
dependency attempts really is refused; nothing is patched. Before this slice the 503 came from
`ConnectionError` and `socket.gaierror` registered globally in `app/main.py`, which answered
"the database is unavailable" for any route that raised a bare `ConnectionResetError` whether or
not a database was involved (IAN-169). The classification now lives at the one place a connect
happens, and this test is what proves a real outage still reaches the right code.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.constants.error_codes import ErrorCode

READ_PATH = "/test-only/connection/read"

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]


def build_test_only_router() -> APIRouter:
    """Return a router with one route that needs a connection it will never get."""
    from app.db.session import get_connection  # noqa: PLC0415

    router = APIRouter()

    @router.get(READ_PATH)
    async def read_through_connection(
        connection: Annotated[AsyncConnection, Depends(get_connection, scope="function")],
    ) -> dict[str, int]:
        """Try a real query through the request connection."""
        return {"answer": int(await connection.scalar(text("SELECT 1")) or 0)}

    return router


@pytest.mark.parametrize("environment", ["production", "development"])
async def test_b9_a_route_taking_get_connection_answers_503_when_the_database_is_unreachable(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    environment: str,
    database_url: str,
) -> None:
    """B-9: the refused connect answers 503 SERVER_DATABASE_UNAVAILABLE, never a 500."""
    application = build_server_app(
        test_only_router=build_test_only_router(),
        environment=environment,
        database_url=database_url,
    )

    async with build_api_client(application) as client:
        response = await client.get(READ_PATH)

    assert response.status_code == 503, response.text
    response_body = response.json()
    assert set(response_body) == {"code", "error"}, response_body
    assert isinstance(response_body["error"], str) and response_body["error"]
    assert response_body["code"] == ErrorCode.SERVER_DATABASE_UNAVAILABLE


async def test_a_bare_connection_error_from_a_route_is_not_reported_as_a_database_outage(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
) -> None:
    """IAN-169: a route raising `ConnectionResetError` answers 500, not 503.

    `builtins.ConnectionError` covers every socket peer failure, database or not. While it was
    registered globally a failing outbound HTTP or Redis call would have told the client the
    database was down and pointed the operator at the wrong dependency.
    """
    router = APIRouter()

    @router.get("/test-only/raise-connection-reset")
    async def raise_connection_reset() -> dict[str, str]:
        """Raise a socket error unrelated to PostgreSQL."""
        raise ConnectionResetError("the peer hung up")

    application = build_server_app(test_only_router=router, environment="production")

    async with build_api_client(application) as client:
        response = await client.get("/test-only/raise-connection-reset")

    assert response.status_code == 500, response.text
    assert response.json()["code"] == ErrorCode.SERVER_INTERNAL_ERROR
