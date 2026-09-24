"""The idempotency middleware is layer 7: innermost, directly inside the CSRF guard.

Innermost because it must capture the final response the route produced, and inside every guard
because a request the rate limiter, the timeout, or the CSRF guard refuses must never claim a key.
"""

from fastapi import FastAPI


def test_idempotency_is_the_innermost_middleware_directly_inside_the_csrf_guard(
    server_app: FastAPI,
) -> None:
    """Starlette lists user middleware outermost first, so the last two entries are 6 and 7."""
    from app.middleware.csrf_guard import CsrfGuardMiddleware  # noqa: PLC0415

    layer_classes = [entry.cls for entry in server_app.user_middleware]
    layer_names = [getattr(layer, "__name__", "") for layer in layer_classes]

    assert layer_names[-1] == "IdempotencyMiddleware", layer_names
    assert layer_classes[-2] is CsrfGuardMiddleware
