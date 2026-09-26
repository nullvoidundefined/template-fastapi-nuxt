"""B-7 against the real Redis: the two buckets, the exemptions, and one atomic counter.

The counts live in Redis rather than in the process, because two replicas sharing a limit is the
whole point of putting them there: a per-process counter multiplies the effective limit by the
replica count. These tests therefore run against the Redis `TEST_REDIS_URL` names, on a database
the fixtures flush first, and read its keys directly where the observable behavior alone cannot
distinguish a correct implementation from one that happens to look correct in a sequential test.

`UNROUTED_PATH` is a path no router will ever mount, so the requests that the limiter allows
answer 404 and say so: the limiter runs before routing, and a request it lets through reaches the
router whether or not a handler is mounted there. The auth paths are asserted as "not 429" for the
opposite reason, since slice 03 mounts real handlers on them and the status they then answer is
not this slice's business.
"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from redis.asyncio import Redis

# Named here rather than imported from the conftest, so this module needs no package import of
# the fixture file that pytest loads for it.
RateLimitAppFactory = Callable[..., Any]
RateLimitClientFactory = Callable[..., Any]

AUTH_PATHS = [
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
]
# Deliberately outside the auth bucket: a signed-in page calls it on every navigation, so ten in
# fifteen minutes would sign the user out for browsing.
SESSION_PATH = "/v1/auth/me"
UNROUTED_PATH = "/v1/rate-limit-probe"
HEALTH_PATH = "/health"
READINESS_PATH = "/health/ready"
WEBHOOK_PATH = "/v1/billing/webhook"
AUTH_REQUEST_LIMIT = 10
GLOBAL_REQUEST_LIMIT = 100
RATE_LIMIT_WINDOW_SECONDS = 900
RATE_LIMIT_EXCEEDED_MESSAGE = "Too many requests"
RATE_LIMIT_EXCEEDED_ENVELOPE = {
    "code": "RATE_LIMIT_EXCEEDED",
    "error": RATE_LIMIT_EXCEEDED_MESSAGE,
}
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CLIENT_ADDRESS = "203.0.113.10"
# The key one client's global bucket lives under, spelled out rather than imported, because it is
# the name the limiter writes into Redis and a test that derived it could not catch it changing.
GLOBAL_BUCKET_KEY_PREFIX = "ratelimit:global"
COUNT_BELOW_THE_GLOBAL_LIMIT = 5
# What Redis reports for a key that exists with no expiry set.
NO_EXPIRY_TTL = -1
# Long enough that a TTL read a second time has visibly fallen, which is how a window that slides
# on every request is told apart from the fixed one the spec fixes.
TTL_OBSERVATION_DELAY_SECONDS = 1.2


@pytest.mark.integration
@pytest.mark.parametrize("auth_path", AUTH_PATHS)
async def test_b7_the_eleventh_request_to_an_auth_path_answers_429_with_retry_after(
    auth_path: str,
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """Ten requests in the window pass on each of the four paths, and the eleventh does not."""
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        allowed = [
            await client.post(auth_path, headers=CSRF_HEADERS) for _ in range(AUTH_REQUEST_LIMIT)
        ]
        rejected = await client.post(auth_path, headers=CSRF_HEADERS)

    assert all(response.status_code != 429 for response in allowed)
    assert allowed[-1].status_code != 429
    assert rejected.status_code == 429
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert 0 < int(rejected.headers["Retry-After"]) <= RATE_LIMIT_WINDOW_SECONDS


@pytest.mark.integration
async def test_b7_the_hundred_and_first_request_of_any_kind_answers_429(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """The global bucket counts every route, including a path no router serves."""
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        allowed = [await client.get(UNROUTED_PATH) for _ in range(GLOBAL_REQUEST_LIMIT)]
        rejected = await client.get(UNROUTED_PATH)

    assert all(response.status_code == 404 for response in allowed)
    assert rejected.status_code == 429
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert 0 < int(rejected.headers["Retry-After"]) <= RATE_LIMIT_WINDOW_SECONDS


@pytest.mark.integration
async def test_b7_the_session_route_is_outside_the_auth_bucket_and_inside_the_global_one(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """`/v1/auth/me` survives its eleventh call and still runs out at the hundred and first."""
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        allowed = [await client.get(SESSION_PATH) for _ in range(GLOBAL_REQUEST_LIMIT)]
        rejected = await client.get(SESSION_PATH)

    assert allowed[AUTH_REQUEST_LIMIT].status_code != 429, "the session route is not auth-limited"
    assert all(response.status_code != 429 for response in allowed)
    assert rejected.status_code == 429
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE


@pytest.mark.integration
async def test_b7_health_routes_and_the_webhook_are_served_after_the_global_limit_is_spent(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """An orchestrator's probe and Stripe's delivery must not depend on a client's budget."""
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        for _ in range(GLOBAL_REQUEST_LIMIT):
            await client.get(UNROUTED_PATH)
        exhausted = await client.get(UNROUTED_PATH)
        liveness = await client.get(HEALTH_PATH)
        readiness = await client.get(READINESS_PATH)
        webhook = await client.post(WEBHOOK_PATH, headers=CSRF_HEADERS)

    assert exhausted.status_code == 429, "the global bucket must be spent for this to mean anything"
    assert liveness.status_code == 200
    assert readiness.status_code in {200, 503}
    # The webhook answers for itself: an unsigned delivery is refused by the route (B-42), which
    # proves the limiter let it through. A 429 here would mean the budget reached it.
    assert webhook.status_code == 400
    assert webhook.json()["code"] == "BILLING_WEBHOOK_MISCONFIGURED"
    for exempt_response in (liveness, readiness, webhook):
        assert exempt_response.status_code != 429
        assert exempt_response.json().get("code") != "RATE_LIMIT_EXCEEDED"


@pytest.mark.integration
async def test_b7_eleven_parallel_requests_on_one_bucket_produce_exactly_one_rejection(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """Every other case here is sequential, so only this one fails a read-then-write counter.

    Eleven requests are issued together against a bucket of ten. A counter that reads the current
    value, decides, and writes the new one gives all eleven the same starting value, so all eleven
    are allowed and no request is rejected. Only a single atomic increment can answer exactly one
    of them with 429 while serving exactly ten.
    """
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        responses = await asyncio.gather(
            *(
                client.post(AUTH_PATHS[0], headers=CSRF_HEADERS)
                for _ in range(AUTH_REQUEST_LIMIT + 1)
            )
        )

    statuses = [response.status_code for response in responses]
    assert statuses.count(429) == 1, statuses
    assert len([status for status in statuses if status != 429]) == AUTH_REQUEST_LIMIT, statuses
    rejection = next(response for response in responses if response.status_code == 429)
    assert rejection.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert 0 < int(rejection.headers["Retry-After"]) <= RATE_LIMIT_WINDOW_SECONDS


@pytest.mark.integration
async def test_b7_every_bucket_key_expires_and_its_window_does_not_slide(
    rate_limit_redis_url: str,
    rate_limit_redis_client: Redis,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """The first request must set the expiry, and a later one must not push it back.

    A key written without an expiry, or with one attached only on some later call, counts a client
    forever: one request every ten minutes would accumulate to the limit and lock the client out
    permanently. Reading the TTL straight after the first request catches the first case, and
    comparing it with the TTL a second later catches the second, because a window re-armed on
    every request never falls.
    """
    application = build_rate_limit_app(rate_limit_redis_url)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        await client.post(AUTH_PATHS[0], headers=CSRF_HEADERS)
        bucket_keys = await rate_limit_redis_client.keys("*")
        first_ttls = {key: await rate_limit_redis_client.ttl(key) for key in bucket_keys}
        await asyncio.sleep(TTL_OBSERVATION_DELAY_SECONDS)
        await client.post(AUTH_PATHS[0], headers=CSRF_HEADERS)
        later_ttls = {key: await rate_limit_redis_client.ttl(key) for key in bucket_keys}

    assert bucket_keys, "the first request must write its bucket keys to Redis"
    assert all(0 < ttl <= RATE_LIMIT_WINDOW_SECONDS for ttl in first_ttls.values()), first_ttls
    assert all(later_ttls[key] < first_ttls[key] for key in bucket_keys), (first_ttls, later_ttls)


@pytest.mark.integration
async def test_b7_a_bucket_key_that_carries_no_expiry_is_armed_by_the_next_request(
    rate_limit_redis_url: str,
    rate_limit_redis_client: Redis,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """A key found without a TTL must get one, or its client is locked out for good.

    A bucket key can exist without an expiry however carefully the increment is written: a restore
    from a dump, a key set by hand during an incident, or a Redis that lost the expiry while
    keeping the value. A script that armed the window only when the counter was new left such a
    key counting forever, so the client behind it reached the limit once and was refused from then
    on, with nothing to reset it but a manual delete. Arming whenever the TTL is negative is what
    makes the window self-healing, and the key here starts at a count below the limit so the
    request is served and the TTL is the only thing under test.
    """
    application = build_rate_limit_app(rate_limit_redis_url)
    bucket_key = f"{GLOBAL_BUCKET_KEY_PREFIX}:{CLIENT_ADDRESS}"
    await rate_limit_redis_client.set(bucket_key, COUNT_BELOW_THE_GLOBAL_LIMIT)
    ttl_before_request = await rate_limit_redis_client.ttl(bucket_key)

    async with open_rate_limited_client(application, CLIENT_ADDRESS) as client:
        served = await client.get(UNROUTED_PATH)

    ttl_after_request = await rate_limit_redis_client.ttl(bucket_key)
    assert ttl_before_request == NO_EXPIRY_TTL, "the key must start without an expiry"
    assert served.status_code == 404, "a count below the limit is still served"
    assert 0 < ttl_after_request <= RATE_LIMIT_WINDOW_SECONDS, ttl_after_request
