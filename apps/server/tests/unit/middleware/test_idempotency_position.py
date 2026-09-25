"""The idempotency middleware is layer 7: innermost, directly inside the CSRF guard.

Innermost because it must capture the final response the route produced, and inside every guard
because a request the rate limiter, the timeout, or the CSRF guard refuses must never claim a key.
"""

from typing import cast

import httpx
from fastapi import FastAPI


def test_idempotency_is_the_innermost_middleware_directly_inside_the_csrf_guard(
    server_app: FastAPI,
) -> None:
    """Starlette lists user middleware outermost first, so the last two entries are 6 and 7."""
    from app.middleware.csrf_guard import CsrfGuardMiddleware  # noqa: PLC0415

    # Starlette types _MiddlewareFactory generically; every entry is really a concrete class.
    layer_classes = [cast(type[object], entry.cls) for entry in server_app.user_middleware]
    layer_names = [getattr(layer, "__name__", "") for layer in layer_classes]

    assert layer_names[-1] == "IdempotencyMiddleware", layer_names
    assert layer_classes[-2] is CsrfGuardMiddleware


async def test_a_keyed_request_the_csrf_guard_refuses_never_reaches_the_claim_table(
    api_client: httpx.AsyncClient,
) -> None:
    """The guard answers before the key is read, so no claim can be written for it.

    The app's database is a closed port. A signed-in, keyed POST that reached the idempotency
    layer would have to look its session up there first and would answer 503; the guard's 403
    is proof that nothing touched the database, so nothing could have claimed the key.
    """
    from app.constants.session import SESSION_COOKIE_NAME  # noqa: PLC0415

    response = await api_client.post(
        "/v1/auth/logout",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "refused-before-claim",
            "Cookie": f"{SESSION_COOKIE_NAME}=any-session-token",
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "CSRF_HEADER_MISSING"
