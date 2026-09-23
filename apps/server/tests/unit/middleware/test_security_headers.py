"""Security headers must protect successful and rejected responses in every environment."""

import httpx
import pytest
from starlette.responses import Response

from tests.conftest import ApiClientFactory, ServerAppFactory


@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
async def test_downstream_managed_headers_are_replaced_and_unrelated_headers_survive(
    environment: str,
) -> None:
    """Raw headers must contain only authoritative values, with HSTS only in production."""
    from app.middleware.security_headers import SecurityHeadersMiddleware  # noqa: PLC0415

    downstream_response = Response()
    downstream_response.raw_headers.extend(
        [
            (b"X-Content-Type-Options", b"downstream-value"),
            (b"Strict-Transport-Security", b"max-age=1"),
            (b"X-Downstream-Marker", b"unchanged"),
        ]
    )
    application = SecurityHeadersMiddleware(downstream_response, environment=environment)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/test-only/downstream-headers")

    assert [
        value for name, value in response.headers.raw if name.lower() == b"x-content-type-options"
    ] == [b"nosniff"]
    assert [
        value
        for name, value in response.headers.raw
        if name.lower() == b"strict-transport-security"
    ] == ([b"max-age=63072000; includeSubDomains"] if environment == "production" else [])
    assert [
        value for name, value in response.headers.raw if name.lower() == b"x-downstream-marker"
    ] == [b"unchanged"]


@pytest.mark.parametrize("status_code", [200, 403, 404, 500])
@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
async def test_every_response_carries_security_headers_and_only_production_enables_hsts(
    status_code: int, environment: str
) -> None:
    """B-35 requires response protection regardless of status or deployment environment."""
    from app.middleware.security_headers import SecurityHeadersMiddleware  # noqa: PLC0415

    application = SecurityHeadersMiddleware(
        Response(status_code=status_code), environment=environment
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/test-only/headers")

    assert response.status_code == status_code
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy")
    if environment == "production":
        assert response.headers.get("Strict-Transport-Security")
    else:
        assert "Strict-Transport-Security" not in response.headers


async def test_cors_preflight_allows_the_configured_origin_and_never_another_origin(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An allowed-origin control prevents absent CORS middleware from passing this test."""
    monkeypatch.setenv("CORS_ORIGIN", "https://client.example")
    application = build_server_app()
    async with build_api_client(application) as client:
        allowed = await client.options(
            "/health",
            headers={
                "Origin": "https://client.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        denied = await client.options(
            "/health",
            headers={
                "Origin": "https://other.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert allowed.headers.get("Access-Control-Allow-Origin") == "https://client.example"
    assert allowed.headers.get("Access-Control-Allow-Credentials") == "true"
    assert "Access-Control-Allow-Origin" not in denied.headers
