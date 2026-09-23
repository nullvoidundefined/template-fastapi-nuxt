"""Require the guard's own csrf_header_missing event to carry the bound request ID.

The generic CSRF denial gives the client no detail, so the guard must log its reason for
operators. RequestContextMiddleware at position 1b binds request_id before the guard runs.
Moving it inside the guard leaves rejection logs without that context and fails the log
assertion. The outer correlation-ID and security-header middleware still decorate the
response under either order, so the header assertions alone cannot distinguish them.
"""

from typing import Any

import httpx
from fastapi import FastAPI


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
