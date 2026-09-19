"""Unit tests for enforcing the body cap before the route runs (Copilot 4052684572, spec B-43).

Spec B-43: a request body over 100 KB answers 413 `INPUT_PAYLOAD_TOO_LARGE` before the route runs.
Counting only the bytes the app chooses to read lets an oversized streamed body through whenever
the route never reads its body, and lets such a route run to completion. These tests stream the
body from an async generator, so httpx sends it chunked without Content-Length, and assert that a
GET-only route answers 413 rather than 405 and that a POST route that ignores its body never runs.
"""

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

OVERSIZED_BODY_BYTES = 101 * 1024
STREAM_CHUNK_BYTES = 8 * 1024
IGNORED_BODY_PATH = "/test-only/ignores-body"
PAYLOAD_TOO_LARGE_CODE = "INPUT_PAYLOAD_TOO_LARGE"


async def stream_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    """Yield a body of total_bytes in fixed chunks, so httpx sends it without Content-Length."""
    remaining_bytes = total_bytes
    while remaining_bytes > 0:
        chunk_bytes = min(STREAM_CHUNK_BYTES, remaining_bytes)
        remaining_bytes -= chunk_bytes
        yield b"x" * chunk_bytes


def mount_body_ignoring_route(application: FastAPI, route_runs: list[str]) -> None:
    """Add a test-only POST route that never reads its body and records each time it runs."""

    async def record_route_run() -> dict[str, str]:
        route_runs.append("ran")
        return {"status": "ran"}

    application.add_api_route(IGNORED_BODY_PATH, record_route_run, methods=["POST"])


def assert_payload_too_large_envelope(response: httpx.Response) -> None:
    """Assert a 413 whose JSON body is the { code, error } envelope with the right code."""
    assert response.status_code == 413, response.text
    response_body = response.json()
    assert set(response_body) == {"code", "error"}, response_body
    assert response_body["code"] == PAYLOAD_TOO_LARGE_CODE


async def test_copilot_4052684572_b43_streamed_oversized_body_to_get_only_route_answers_413(
    api_client: httpx.AsyncClient,
) -> None:
    """Copilot 4052684572, B-43: a chunked 101 KB POST to GET-only /health answers 413, not 405."""
    response = await api_client.post("/health", content=stream_body_chunks(OVERSIZED_BODY_BYTES))

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert_payload_too_large_envelope(response)


async def test_copilot_4052684572_b43_route_that_ignores_its_body_never_runs_on_oversized_body(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Copilot 4052684572, B-43: a chunked 101 KB body answers 413 and the route never runs."""
    route_runs: list[str] = []
    mount_body_ignoring_route(server_app, route_runs)

    response = await api_client.post(
        IGNORED_BODY_PATH, content=stream_body_chunks(OVERSIZED_BODY_BYTES)
    )

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert_payload_too_large_envelope(response)
    assert route_runs == []
