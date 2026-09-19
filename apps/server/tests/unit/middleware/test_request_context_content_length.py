"""Unit tests for reading a zero-padded Content-Length by value (Copilot 4052759306).

Spec Middleware row: a request body over 100 KB answers 413 `INPUT_PAYLOAD_TOO_LARGE`, judged by
the declared or streamed byte count. A Content-Length header with leading zeros is legal and names
the same number without them, so a long zero-padded header whose value is within the limit must
reach the route rather than being rejected for its digit count. These tests build the request
explicitly so the zero-padded header is sent as written instead of the length httpx computes.
"""

import httpx
from fastapi import FastAPI, Request

BODY_ECHO_PATH = "/test-only/body-byte-count"
LEADING_ZERO_PADDING = "0" * 30
SMALL_BODY = b"hello"


def mount_body_counting_route(application: FastAPI) -> None:
    """Add a test-only POST route that reads its whole body and returns the byte count."""

    async def count_body_bytes(request: Request) -> dict[str, int]:
        request_body = await request.body()
        return {"byte_count": len(request_body)}

    application.add_api_route(BODY_ECHO_PATH, count_body_bytes, methods=["POST"])


async def test_copilot_4052759306_zero_padded_content_length_within_limit_reaches_route(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Copilot 4052759306, spec Middleware row: 30 zeros then `5` with a 5-byte body answers 200."""
    mount_body_counting_route(server_app)
    padded_content_length = f"{LEADING_ZERO_PADDING}{len(SMALL_BODY)}"
    request = api_client.build_request("POST", BODY_ECHO_PATH, content=SMALL_BODY)
    request.headers["Content-Length"] = padded_content_length

    response = await api_client.send(request)

    assert response.request.headers["content-length"] == padded_content_length
    assert response.status_code == 200, response.text
    assert response.json() == {"byte_count": len(SMALL_BODY)}
