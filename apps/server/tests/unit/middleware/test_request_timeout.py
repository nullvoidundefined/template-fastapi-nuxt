"""A slow handler must be cancelled and answered with the timeout error envelope."""

import asyncio

import httpx
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send


async def test_a_handler_exceeding_the_injected_limit_receives_the_exact_timeout_envelope() -> None:
    """B-8 is exercised with a short injected deadline and observable cancellation."""
    from app.middleware.request_timeout import RequestTimeoutMiddleware  # noqa: PLC0415

    cancelled = asyncio.Event()

    async def slow_handler(scope: Scope, receive: Receive, send: Send) -> None:
        """Record cancellation so returning a timeout without stopping work fails."""
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        await JSONResponse({"handler_finished": True})(scope, receive, send)

    application = RequestTimeoutMiddleware(slow_handler, seconds=0.005)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/test-only/slow")
    assert response.status_code == 408
    assert response.json() == {"code": "SERVER_REQUEST_TIMEOUT", "error": "Request timed out"}
    assert cancelled.is_set()
