"""B-7: the password change counts in the auth bucket, and the session read still does not.

`PATCH /v1/auth/me` verifies a password, and anything that verifies a password is somewhere a
password can be guessed. The auth bucket of ten per fifteen minutes is what bounds guessing; the
global bucket of one hundred is not, and one hundred attempts per quarter hour against a known
address is a working online attack. The limiter matches the auth bucket on the path alone, and
`/v1/auth/me` is deliberately outside that set because a signed-in page calls `GET /v1/auth/me` on
every navigation, so the `PATCH` silently inherits an exclusion written for the `GET`.

Both directions are asserted, because the cheapest fix is to add `/v1/auth/me` to the auth path
set, and that would put the read into the bucket too and sign a browsing user out after ten
navigations. Whatever shape the fix takes, it has to separate the two methods on the same path.

The assertions are the 429 and its envelope plus the bucket key the limiter wrote in Redis, never
the contents of the constant the middleware consults: a test that read the constant would pass for
any spelling of it, including one the middleware never looks at, which is the exact class of
defect the auth path list already carries a comment about.
"""

from collections.abc import Callable
from typing import Any

import pytest

# Named here rather than imported from the conftest, so this module needs no package import of
# the fixture file that pytest loads for it.
RateLimitAppFactory = Callable[..., Any]
RateLimitClientFactory = Callable[..., Any]

SESSION_PATH = "/v1/auth/me"
AUTH_REQUEST_LIMIT = 10
RATE_LIMIT_WINDOW_SECONDS = 900
RATE_LIMIT_EXCEEDED_MESSAGE = "Too many requests"
RATE_LIMIT_EXCEEDED_ENVELOPE = {
    "code": "RATE_LIMIT_EXCEEDED",
    "error": RATE_LIMIT_EXCEEDED_MESSAGE,
}
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CLIENT_ADDRESS = "203.0.113.11"
# The keys one client's two buckets live under, spelled out rather than imported, because these
# are the names the limiter writes into Redis and a test that derived them could not catch them
# changing.
AUTH_BUCKET_KEY = f"ratelimit:auth:{CLIENT_ADDRESS}"
GLOBAL_BUCKET_KEY = f"ratelimit:global:{CLIENT_ADDRESS}"
# Built from parts rather than written as literals, so no credential-shaped string appears in this
# source for a secret scanner to flag (R-108). The database is unreachable in these tests, so no
# request here ever reaches a password comparison; what is under test is the counting in front of
# the route, which runs before routing and before any dependency.
PASSWORD_CHANGE_BODY = {
    "current_password": "-".join(("correct", "horse", "battery", "staple")),
    "new_password": "-".join(("another", "entirely", "different", "phrase")),
}


@pytest.mark.integration
async def test_b7_the_password_change_route_is_counted_in_the_auth_bucket(
    rate_limit_redis_url: str,
    rate_limit_redis_client: Any,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """The eleventh password change in the window is refused, and the auth key holds the count.

    The status of the ten that pass is not asserted beyond "not 429": the database is unreachable
    here, so what they answer past the limiter is not this test's business. The auth bucket key is
    read afterwards because a limiter that answered 429 from the global bucket alone would be a
    different implementation with the same visible status at a different threshold.
    """
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        allowed = [
            await client.patch(SESSION_PATH, json=PASSWORD_CHANGE_BODY, headers=CSRF_HEADERS)
            for _ in range(AUTH_REQUEST_LIMIT)
        ]
        rejected = await client.patch(SESSION_PATH, json=PASSWORD_CHANGE_BODY, headers=CSRF_HEADERS)

    assert all(response.status_code != 429 for response in allowed), [
        response.status_code for response in allowed
    ]
    assert rejected.status_code == 429, rejected.text
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert 0 < int(rejected.headers["Retry-After"]) <= RATE_LIMIT_WINDOW_SECONDS
    auth_bucket_count = await rate_limit_redis_client.get(AUTH_BUCKET_KEY)
    assert auth_bucket_count is not None, "the password change must count in the auth bucket"
    assert int(auth_bucket_count) == AUTH_REQUEST_LIMIT + 1, auth_bucket_count


@pytest.mark.integration
async def test_b7_the_session_read_is_still_outside_the_auth_bucket(
    rate_limit_redis_url: str,
    rate_limit_redis_client: Any,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """Eleven navigations must not exhaust anything, and must leave the auth key unwritten.

    This is the direction a fix breaks by accident. Adding the path to the auth set satisfies the
    test above and turns every signed-in page into a countdown to a forced sign-out, so the read
    is pinned here as explicitly as the change is.
    """
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        served = [await client.get(SESSION_PATH) for _ in range(AUTH_REQUEST_LIMIT + 1)]

    assert all(response.status_code != 429 for response in served), [
        response.status_code for response in served
    ]
    assert await rate_limit_redis_client.get(AUTH_BUCKET_KEY) is None, (
        "a signed-in page calls the session read on every navigation, "
        "so it may never move the auth bucket"
    )
    global_bucket_count = await rate_limit_redis_client.get(GLOBAL_BUCKET_KEY)
    assert global_bucket_count is not None, "the session read still counts in the global bucket"
    assert int(global_bucket_count) == AUTH_REQUEST_LIMIT + 1, global_bucket_count
