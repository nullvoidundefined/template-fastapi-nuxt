"""The CSRF guard must reject unsafe requests and exempt only explicitly named paths."""

import httpx
import pytest
from starlette.responses import JSONResponse


async def send_guarded_request(
    method: str, path: str = "/test-only/write", headers: dict[str, str] | None = None
) -> httpx.Response:
    """Construct the missing middleware during the test rather than fixture setup."""
    from app.middleware.csrf_guard import CsrfGuardMiddleware  # noqa: PLC0415

    application = CsrfGuardMiddleware(JSONResponse({"handler_reached": True}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        return await client.request(method, path, headers=headers)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_state_changing_requests_without_the_header_receive_the_exact_csrf_envelope(
    method: str,
) -> None:
    """B-6 requires the registered error code and message rather than a bare denial."""
    response = await send_guarded_request(method)
    assert response.status_code == 403
    assert response.json() == {
        "code": "CSRF_HEADER_MISSING",
        "error": "That request is not allowed",
    }


async def test_post_with_the_required_header_reaches_the_handler() -> None:
    """A legitimate client must still be able to change state."""
    response = await send_guarded_request("POST", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 200
    assert response.json() == {"handler_reached": True}


async def test_get_without_the_header_reaches_the_handler() -> None:
    """A safe request does not require the custom CSRF header."""
    response = await send_guarded_request("GET")
    assert response.status_code == 200
    assert response.json() == {"handler_reached": True}


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/v1/billing/webhook"])
async def test_exact_exempt_paths_reach_the_handler_without_the_header(path: str) -> None:
    """Health checks and the signature-authenticated webhook are explicitly exempt."""
    response = await send_guarded_request("POST", path)
    assert response.status_code == 200
    assert response.json() == {"handler_reached": True}


@pytest.mark.parametrize("path", ["/health/ready-not-really", "/v1/billing/webhook-spoof"])
async def test_paths_sharing_an_exempt_prefix_are_still_guarded(path: str) -> None:
    """Matching exemptions by prefix would expose unrelated state-changing handlers."""
    response = await send_guarded_request("POST", path)
    assert response.status_code == 403
    assert response.json() == {
        "code": "CSRF_HEADER_MISSING",
        "error": "That request is not allowed",
    }
