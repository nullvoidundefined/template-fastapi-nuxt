"""Regression guard for replaying a pre-read body (Copilot 4052684572, spec B-43).

Answering 413 before the route runs (B-43) means the middleware reads the body before the app
does, so it must hand the app every byte it read, in order. This test streams a body of exactly
100 KB, the largest allowed, with content that differs by chunk, to a test-only route that reads
the whole body and answers its length and SHA-256 digest, so a dropped, duplicated, or reordered
chunk in the replay fails it. It passes before and after the fix; it guards the fix, not the gap.
"""

import hashlib
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request

MAX_BODY_BYTES = 100 * 1024
STREAM_CHUNK_BYTES = 8 * 1024
BODY_DIGEST_PATH = "/test-only/body-digest"


def build_varied_body(total_bytes: int) -> bytes:
    """Return total_bytes whose content differs from chunk to chunk."""
    return bytes(offset % 251 for offset in range(total_bytes))


async def stream_fixed_chunks(body: bytes) -> AsyncIterator[bytes]:
    """Yield body in fixed chunks, so httpx sends it without Content-Length."""
    for offset in range(0, len(body), STREAM_CHUNK_BYTES):
        yield body[offset : offset + STREAM_CHUNK_BYTES]


def mount_body_digest_route(application: FastAPI) -> None:
    """Add a test-only POST route that reads the whole body and answers its length and digest."""

    async def read_body_digest(request: Request) -> dict[str, int | str]:
        body = await request.body()
        return {"received_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    application.add_api_route(BODY_DIGEST_PATH, read_body_digest, methods=["POST"])


async def test_copilot_4052684572_b43_pre_read_body_of_exactly_100_kb_is_replayed_intact(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Copilot 4052684572, B-43: a chunked 100 KB body reaches a reading route byte for byte."""
    mount_body_digest_route(server_app)
    request_body = build_varied_body(MAX_BODY_BYTES)

    response = await api_client.post(BODY_DIGEST_PATH, content=stream_fixed_chunks(request_body))

    assert "content-length" not in {name.lower() for name in response.request.headers}
    assert response.status_code == 200
    assert response.json() == {
        "received_bytes": MAX_BODY_BYTES,
        "sha256": hashlib.sha256(request_body).hexdigest(),
    }
