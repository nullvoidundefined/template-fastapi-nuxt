"""Unit tests for the request-context body-size limit (spec Middleware row, R-406).

The middleware rejects a request body over 100 KB with 413. The declared-length cases post to
`/health`, which defines only GET, so a body that passes the limit reaches the router and gets
whatever the router answers, just never 413. The chunked cases, which carry no Content-Length,
use a body-reading route that the test mounts itself, because the limit must hold while the body
streams. The error code INPUT_PAYLOAD_TOO_LARGE belongs to slice 02's envelope and is not
asserted here.
"""

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request

OVERSIZED_BODY_BYTES = 101 * 1024
UNDERSIZED_BODY_BYTES = 99_000
STREAM_CHUNK_BYTES = 8 * 1024
BODY_ECHO_PATH = "/test-only/body-length"


def mount_body_length_route(application: FastAPI) -> None:
    """Add a test-only POST route that reads the whole body and answers its length."""

    async def read_body_length(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"received_bytes": len(body)}

    application.add_api_route(BODY_ECHO_PATH, read_body_length, methods=["POST"])


async def stream_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    """Yield a body of total_bytes in fixed chunks, so httpx sends it without Content-Length."""
    remaining_bytes = total_bytes
    while remaining_bytes > 0:
        chunk_bytes = min(STREAM_CHUNK_BYTES, remaining_bytes)
        remaining_bytes -= chunk_bytes
        yield b"x" * chunk_bytes


async def test_body_over_100_kb_with_content_length_is_rejected_with_413(
    api_client: httpx.AsyncClient,
) -> None:
    """Middleware row: a 101 KB body with a declared Content-Length answers 413."""
    response = await api_client.post("/health", content=b"x" * OVERSIZED_BODY_BYTES)

    assert response.status_code == 413


async def test_body_under_100_kb_with_content_length_passes_the_limit(
    api_client: httpx.AsyncClient,
) -> None:
    """Middleware row: a 99,000-byte body is not rejected with 413."""
    response = await api_client.post("/health", content=b"x" * UNDERSIZED_BODY_BYTES)

    assert response.status_code != 413


async def test_streamed_body_over_100_kb_without_content_length_is_rejected_with_413(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Middleware row, R-406: a chunked 101 KB body with no Content-Length answers 413."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH, content=stream_body_chunks(OVERSIZED_BODY_BYTES)
    )

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert response.status_code == 413


async def test_streamed_body_under_100_kb_reaches_the_route_intact(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Middleware row: a chunked 99,000-byte body reaches the route with every byte."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH, content=stream_body_chunks(UNDERSIZED_BODY_BYTES)
    )

    assert response.status_code == 200
    assert response.json() == {"received_bytes": UNDERSIZED_BODY_BYTES}
