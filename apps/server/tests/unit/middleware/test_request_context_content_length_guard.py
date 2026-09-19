"""Unit tests that a zero-padded oversized Content-Length still answers 413 (Copilot 4052759306).

Spec Middleware row: a request body over 100 KB answers 413 `INPUT_PAYLOAD_TOO_LARGE` before the
route runs, judged by the declared byte count when a Content-Length header is present. Stripping
leading zeros from the header, the fix for Copilot 4052759306, must not let a zero-padded header
that names more than 100 KB through. The request is built explicitly so the zero-padded header is
sent as written, with a small body, so only the declared length can trigger the 413.
"""

import httpx
from fastapi import FastAPI, Request

DECLARED_BODY_PATH = "/test-only/declared-body-byte-count"
LEADING_ZERO_PADDING = "0" * 30
OVER_LIMIT_DECLARED_BYTES = 100 * 1024 + 1
SMALL_BODY = b"hello"
PAYLOAD_TOO_LARGE_CODE = "INPUT_PAYLOAD_TOO_LARGE"


def mount_body_counting_route(application: FastAPI, route_runs: list[str]) -> None:
    """Add a test-only POST route that reads its body, records each run, and returns the count."""

    async def count_body_bytes(request: Request) -> dict[str, int]:
        route_runs.append("ran")
        request_body = await request.body()
        return {"byte_count": len(request_body)}

    application.add_api_route(DECLARED_BODY_PATH, count_body_bytes, methods=["POST"])


async def test_copilot_4052759306_zero_padded_content_length_over_limit_answers_413(
    server_app: FastAPI, api_client: httpx.AsyncClient
) -> None:
    """Copilot 4052759306, spec Middleware row: 30 zeros then `102401` answers 413, route unrun."""
    route_runs: list[str] = []
    mount_body_counting_route(server_app, route_runs)
    padded_content_length = f"{LEADING_ZERO_PADDING}{OVER_LIMIT_DECLARED_BYTES}"
    request = api_client.build_request("POST", DECLARED_BODY_PATH, content=SMALL_BODY)
    request.headers["Content-Length"] = padded_content_length

    response = await api_client.send(request)

    assert response.request.headers["content-length"] == padded_content_length
    assert response.status_code == 413, response.text
    response_body = response.json()
    assert set(response_body) == {"code", "error"}, response_body
    assert response_body["code"] == PAYLOAD_TOO_LARGE_CODE
    assert route_runs == []
