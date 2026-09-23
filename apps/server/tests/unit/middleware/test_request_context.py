"""Unit tests for the request-context middleware (spec Middleware row, B-2, R-406).

The middleware rejects a request body over 100 KB with 413 `INPUT_PAYLOAD_TOO_LARGE` in the
`{ code, error }` envelope, whether the body declares its length or streams without one, and
lets a body of exactly 100 KB through. The `/health` cases post to a GET-only route, so a body
that passes the limit reaches the router and gets its 405. The body-echo and typed-body cases use
routes the test mounts itself, because the limit must hold while the body streams, including
when FastAPI reads the body to validate a Pydantic model. The middleware also binds the request
ID into structlog's context for one request and must restore whatever context the caller had
bound before it, rather than erase it.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
import structlog
from fastapi import FastAPI, Request
from pydantic import BaseModel

MAX_BODY_BYTES = 100 * 1024
OVERSIZED_BODY_BYTES = 101 * 1024
UNDERSIZED_BODY_BYTES = 99_000
STREAM_CHUNK_BYTES = 8 * 1024
HUGE_CONTENT_LENGTH_DIGITS = 5000
BODY_ECHO_PATH = "/test-only/body-length"
TYPED_BODY_PATH = "/test-only/typed-body"
PAYLOAD_TOO_LARGE_CODE = "INPUT_PAYLOAD_TOO_LARGE"
OUTER_REQUEST_ID = "outer-job-42"
TEST_BASE_URL = "http://testserver"


class TypedBodyPayload(BaseModel):
    """Test-only request model, so FastAPI reads and validates the body itself."""

    text: str


def mount_body_length_route(application: FastAPI) -> None:
    """Add a test-only POST route that reads the whole body and answers its length."""

    async def read_body_length(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"received_bytes": len(body)}

    application.add_api_route(BODY_ECHO_PATH, read_body_length, methods=["POST"])


def mount_typed_body_route(application: FastAPI) -> None:
    """Add a test-only POST route whose parameter is a Pydantic model."""

    async def read_typed_body(payload: TypedBodyPayload) -> dict[str, int]:
        return {"text_length": len(payload.text)}

    application.add_api_route(TYPED_BODY_PATH, read_typed_body, methods=["POST"])


async def stream_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    """Yield a body of total_bytes in fixed chunks, so httpx sends it without Content-Length."""
    remaining_bytes = total_bytes
    while remaining_bytes > 0:
        chunk_bytes = min(STREAM_CHUNK_BYTES, remaining_bytes)
        remaining_bytes -= chunk_bytes
        yield b"x" * chunk_bytes


async def stream_json_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    """Yield a valid JSON object of total_bytes in fixed chunks, without Content-Length."""
    prefix = b'{"text": "'
    suffix = b'"}'
    json_body = prefix + b"x" * (total_bytes - len(prefix) - len(suffix)) + suffix
    for offset in range(0, len(json_body), STREAM_CHUNK_BYTES):
        yield json_body[offset : offset + STREAM_CHUNK_BYTES]


def build_request_body(total_bytes: int, is_streamed: bool) -> bytes | AsyncIterator[bytes]:
    """Return a body of total_bytes, streamed without Content-Length or sent with one."""
    if is_streamed:
        return stream_body_chunks(total_bytes)
    return b"x" * total_bytes


def assert_payload_too_large_envelope(response: httpx.Response) -> None:
    """Assert a 413 whose JSON body is the { code, error } envelope with the right code."""
    assert response.status_code == 413
    response_body = response.json()
    assert set(response_body) == {"code", "error"}, response_body
    assert response_body["code"] == PAYLOAD_TOO_LARGE_CODE
    assert isinstance(response_body["error"], str)
    assert response_body["error"].strip()


async def test_body_over_100_kb_with_content_length_is_rejected_with_413(
    api_client: httpx.AsyncClient,
) -> None:
    """Middleware row: a 101 KB body with a declared Content-Length answers 413."""
    response = await api_client.post("/health", content=b"x" * OVERSIZED_BODY_BYTES)

    assert response.status_code == 413


async def test_body_under_100_kb_with_content_length_passes_the_limit(
    api_client: httpx.AsyncClient,
) -> None:
    """Middleware row, defect 4: a 99,000-byte body passes the limit and gets the router's 405."""
    response = await api_client.post("/health", content=b"x" * UNDERSIZED_BODY_BYTES)

    assert response.status_code == 405


async def test_streamed_body_over_100_kb_without_content_length_is_rejected_with_413(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Middleware row, R-406: a chunked 101 KB body with no Content-Length answers 413."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH,
        content=stream_body_chunks(OVERSIZED_BODY_BYTES),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert response.status_code == 413


async def test_streamed_body_under_100_kb_reaches_the_route_intact(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Middleware row: a chunked 99,000-byte body reaches the route with every byte."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH,
        content=stream_body_chunks(UNDERSIZED_BODY_BYTES),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json() == {"received_bytes": UNDERSIZED_BODY_BYTES}


async def test_defect2_streamed_body_over_100_kb_to_a_pydantic_route_is_rejected_with_413(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Defect 2, Middleware row, R-406: a chunked 101 KB JSON body to a typed route answers 413."""
    mount_typed_body_route(server_app)

    response = await api_client.post(
        TYPED_BODY_PATH,
        content=stream_json_body_chunks(OVERSIZED_BODY_BYTES),
        headers={"content-type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert response.status_code == 413


@pytest.mark.parametrize("is_streamed", [False, True], ids=["declared", "streamed"])
async def test_defect4_body_of_exactly_100_kb_reaches_the_route_intact(
    server_app: FastAPI, api_client: httpx.AsyncClient, is_streamed: bool
) -> None:
    """Defect 4, Middleware row: a body of exactly 100 * 1024 bytes is inside the limit."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH,
        content=build_request_body(MAX_BODY_BYTES, is_streamed),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json() == {"received_bytes": MAX_BODY_BYTES}


@pytest.mark.parametrize("is_streamed", [False, True], ids=["declared", "streamed"])
async def test_defect4_body_one_byte_over_100_kb_is_rejected_with_413(
    server_app: FastAPI, api_client: httpx.AsyncClient, is_streamed: bool
) -> None:
    """Defect 4, Middleware row: a body of 100 * 1024 + 1 bytes answers 413."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH,
        content=build_request_body(MAX_BODY_BYTES + 1, is_streamed),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 413


async def test_defect7_huge_declared_content_length_is_rejected_with_413(
    server_app: FastAPI,
) -> None:
    """Defect 7, Middleware row, R-406: a 5,000-digit Content-Length answers 413, not a 500."""
    huge_content_length = "9" * HUGE_CONTENT_LENGTH_DIGITS
    async with server_app.router.lifespan_context(server_app):
        transport = httpx.ASGITransport(app=server_app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
            response = await client.post(
                "/health", content=b"", headers={"content-length": huge_content_length}
            )

    assert response.request.headers["content-length"] == huge_content_length
    assert response.status_code == 413


@pytest.mark.parametrize("is_streamed", [False, True], ids=["declared", "streamed"])
async def test_defect8_every_413_uses_the_input_payload_too_large_envelope(
    server_app: FastAPI, api_client: httpx.AsyncClient, is_streamed: bool
) -> None:
    """Defect 8, Middleware row: a 413 body is {"code": "INPUT_PAYLOAD_TOO_LARGE", "error": ...}."""
    mount_body_length_route(server_app)

    response = await api_client.post(
        BODY_ECHO_PATH,
        content=build_request_body(OVERSIZED_BODY_BYTES, is_streamed),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert_payload_too_large_envelope(response)


async def test_defect6_b2_request_restores_the_outer_request_id_context_afterwards(
    api_client: httpx.AsyncClient,
) -> None:
    """Defect 6, B-2: a request_id bound before a request is still bound after it."""
    structlog.contextvars.bind_contextvars(request_id=OUTER_REQUEST_ID)
    try:
        response = await api_client.get("/health")
        restored_context = structlog.contextvars.get_contextvars()
    finally:
        structlog.contextvars.clear_contextvars()

    assert response.status_code == 200
    assert restored_context.get("request_id") == OUTER_REQUEST_ID
