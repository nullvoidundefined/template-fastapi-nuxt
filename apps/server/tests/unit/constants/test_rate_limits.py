"""B-7: the published rate-limit buckets, the limited auth paths, and the exempt paths.

The behavior tests count requests, so on their own they cannot say which numbers the spec fixed
or where those numbers are written down. These assertions pin the constants themselves: one
hundred requests per fifteen minutes globally, ten per fifteen minutes on exactly the four auth
paths written with the `/v1` mount prefix the middleware actually sees, and the two health routes
plus the Stripe webhook exempt from both buckets. The exempt set lives beside the CSRF guard's own
exemptions in `app.constants.exempt_paths`, because the two guards exempt the same three paths for
the same reasons and two separate lists would drift.

Every import happens inside a test body, so a missing module fails the test that needs it rather
than erroring the whole collection.
"""

AUTH_RATE_LIMITED_PATH_VALUES = {
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
}
RATE_LIMIT_EXEMPT_PATH_VALUES = {"/health", "/health/ready", "/v1/billing/webhook"}


def test_b7_the_two_buckets_carry_the_limits_and_the_window_the_spec_fixed() -> None:
    """One hundred requests globally and ten on the auth paths, both per fifteen minutes."""
    from app.constants.rate_limits import (  # noqa: PLC0415 (missing until implemented)
        AUTH_REQUEST_LIMIT,
        GLOBAL_REQUEST_LIMIT,
        RATE_LIMIT_WINDOW_SECONDS,
    )

    assert GLOBAL_REQUEST_LIMIT == 100
    assert AUTH_REQUEST_LIMIT == 10
    assert RATE_LIMIT_WINDOW_SECONDS == 15 * 60


def test_b7_the_auth_bucket_names_the_four_paths_in_full() -> None:
    """A pattern written without the `/v1` prefix never matches the path the middleware sees."""
    from app.constants.rate_limits import (  # noqa: PLC0415 (missing until implemented)
        AUTH_RATE_LIMITED_PATHS,
    )

    assert set(AUTH_RATE_LIMITED_PATHS) == AUTH_RATE_LIMITED_PATH_VALUES


def test_b7_the_exempt_set_is_the_health_routes_and_the_webhook() -> None:
    """Both buckets skip liveness, readiness, and the signature-authenticated webhook."""
    from app.constants.exempt_paths import (  # noqa: PLC0415 (missing until implemented)
        RATE_LIMIT_EXEMPT_PATHS,
    )

    assert set(RATE_LIMIT_EXEMPT_PATHS) == RATE_LIMIT_EXEMPT_PATH_VALUES
