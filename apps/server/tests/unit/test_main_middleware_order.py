"""Require the guard's own csrf_header_missing event to carry the bound request ID.

The generic CSRF denial gives the client no detail, so the guard must log its reason for
operators. RequestContextMiddleware at position 1b binds request_id before the guard runs.
Moving it inside the guard leaves rejection logs without that context and fails the log
assertion. The outer correlation-ID and security-header middleware still decorate the
response under either order, so the header assertions alone cannot distinguish them.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import ApiClientFactory, ServerAppFactory


async def test_body_limit_rejection_carries_security_headers(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
) -> None:
    """The real application's body guard must decorate its own early 413 response."""
    application = build_server_app()
    async with build_api_client(application) as client:
        response = await client.post("/health", content=b"x" * (100 * 1024 + 1))

    assert response.status_code == 413
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


@pytest.mark.parametrize("environment", ["development", "production"])
async def test_unhandled_failure_carries_security_headers(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    environment: str,
) -> None:
    """The outer server-error response must retain the environment's security headers."""
    application = build_server_app(environment=environment)

    async def raise_unhandled_error() -> None:
        """Trigger the application's unhandled-exception handler."""
        raise RuntimeError("Test-only unhandled failure")

    application.add_api_route("/test-only/unhandled", raise_unhandled_error)
    async with build_api_client(application) as client:
        response = await client.get("/test-only/unhandled")

    assert response.status_code == 500
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    if environment == "production":
        assert response.headers["Strict-Transport-Security"] == (
            "max-age=63072000; includeSubDomains"
        )
    else:
        assert "Strict-Transport-Security" not in response.headers


async def test_csrf_rejections_carry_security_headers_and_log_with_the_bound_request_id(
    server_app: FastAPI,
    api_client: httpx.AsyncClient,
    captured_log_events: list[dict[str, Any]],
) -> None:
    """Require csrf_header_missing to inherit request context during the guard's rejection."""

    async def write_value() -> dict[str, bool]:
        """Return success only if the guard allows the request through."""
        return {"handler_reached": True}

    server_app.add_api_route("/test-only/order", write_value, methods=["POST"])
    captured_log_events.clear()
    response = await api_client.post("/test-only/order", headers={"X-Request-Id": "csrf-order-42"})
    assert response.status_code == 403
    assert response.json() == {
        "code": "CSRF_HEADER_MISSING",
        "error": "That request is not allowed",
    }
    assert response.headers.get("X-Request-Id") == "csrf-order-42"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy")
    rejection_events = [
        event for event in captured_log_events if event.get("event") == "csrf_header_missing"
    ]
    assert rejection_events, "The CSRF guard must emit its own csrf_header_missing rejection event"
    assert all(event.get("request_id") == "csrf-order-42" for event in rejection_events)
