"""B-7 key derivation: the bucket follows the address uvicorn resolved, never a raw header.

A limiter keyed on a header the client controls is not a limiter, so these are the tests the
review focus is about. They are driven through uvicorn's own `ProxyHeadersMiddleware` rather than
through the suite's bare `httpx.ASGITransport`, because that transport never runs the proxy-header
handling the deployed process does: under it, `scope["client"]` is whatever the transport was
given and `X-Forwarded-For` is left in the headers untouched. A forged-header assertion driven
that way would pass whether or not the limiter parsed the header itself, which is the one failure
this file exists to rule out.

The wrapper trusts exactly `PROXY_ADDRESS`, matching the `FORWARDED_ALLOW_IPS` the application is
built with, and mirrors the deployed chain: the edge appends the connecting address as the last
`X-Forwarded-For` entry, the Nitro proxy forwards that entry, and uvicorn walks the list from the
right past its trusted addresses. Everything to the left of the last entry is client-supplied, so
a client that prepends entries changes nothing about which bucket it lands in, and a request that
reaches the application from anywhere other than the proxy is keyed on its own peer address with
its header ignored.
"""

from collections.abc import Callable
from typing import Any

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Named here rather than imported from the conftest, so this module needs no package import of
# the fixture file that pytest loads for it.
RateLimitAppFactory = Callable[..., Any]
RateLimitClientFactory = Callable[..., Any]

AUTH_PATH = "/v1/auth/login"
AUTH_REQUEST_LIMIT = 10
RATE_LIMIT_EXCEEDED_MESSAGE = "Too many requests"
RATE_LIMIT_EXCEEDED_ENVELOPE = {
    "code": "RATE_LIMIT_EXCEEDED",
    "error": RATE_LIMIT_EXCEEDED_MESSAGE,
}
CSRF_HEADER = {"X-Requested-With": "XMLHttpRequest"}
# Must match the conftest's PROXY_ADDRESS, which is also the application's FORWARDED_ALLOW_IPS.
PROXY_ADDRESS = "10.10.0.2"
FIRST_CLIENT_ADDRESS = "203.0.113.10"
SECOND_CLIENT_ADDRESS = "203.0.113.11"
DIRECT_CLIENT_ADDRESS = "203.0.113.20"
OTHER_DIRECT_CLIENT_ADDRESS = "203.0.113.21"
# The addresses a client writes into the header itself, hoping to be counted as somebody else.
FORGED_ADDRESS = "198.51.100.66"
OTHER_FORGED_ADDRESS = "198.51.100.77"


def build_forwarded_headers(forwarded_for: str) -> dict[str, str]:
    """Return the CSRF header plus one `X-Forwarded-For` chain to send with a request."""
    return {**CSRF_HEADER, "X-Forwarded-For": forwarded_for}


@pytest.mark.integration
async def test_b7_two_client_addresses_arriving_through_the_proxy_count_in_two_buckets(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """One client spending its auth budget must not spend the budget of the next one."""
    application = build_rate_limit_app(rate_limit_redis_url)
    proxied_application = ProxyHeadersMiddleware(application, trusted_hosts=PROXY_ADDRESS)

    async with open_rate_limited_client(application, PROXY_ADDRESS, proxied_application) as client:
        first_client_headers = build_forwarded_headers(FIRST_CLIENT_ADDRESS)
        allowed = [
            await client.post(AUTH_PATH, headers=first_client_headers)
            for _ in range(AUTH_REQUEST_LIMIT)
        ]
        rejected = await client.post(AUTH_PATH, headers=first_client_headers)
        second_client_response = await client.post(
            AUTH_PATH, headers=build_forwarded_headers(SECOND_CLIENT_ADDRESS)
        )

    assert all(response.status_code != 429 for response in allowed)
    assert rejected.status_code == 429
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert second_client_response.status_code != 429


@pytest.mark.integration
async def test_b7_a_client_prepending_forged_entries_is_counted_in_its_own_bucket(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """Rotating the forged prefix must neither reset the client's bucket nor spend another's.

    The client sends its ten requests behind one forged entry and its eleventh behind a different
    one. A limiter reading the leftmost entry would see the eleventh as a first request from a new
    address and serve it, and would also have charged the forged address for the first ten, so the
    request that genuinely comes from that address would be rejected. Both assertions below fail
    against that implementation, and both pass only when the header is ignored entirely.
    """
    application = build_rate_limit_app(rate_limit_redis_url)
    proxied_application = ProxyHeadersMiddleware(application, trusted_hosts=PROXY_ADDRESS)

    async with open_rate_limited_client(application, PROXY_ADDRESS, proxied_application) as client:
        forged_chain = f"{FORGED_ADDRESS}, {FIRST_CLIENT_ADDRESS}"
        allowed = [
            await client.post(AUTH_PATH, headers=build_forwarded_headers(forged_chain))
            for _ in range(AUTH_REQUEST_LIMIT)
        ]
        rotated_chain = f"{OTHER_FORGED_ADDRESS}, {FIRST_CLIENT_ADDRESS}"
        rejected = await client.post(AUTH_PATH, headers=build_forwarded_headers(rotated_chain))
        forged_address_response = await client.post(
            AUTH_PATH, headers=build_forwarded_headers(FORGED_ADDRESS)
        )

    assert all(response.status_code != 429 for response in allowed)
    assert rejected.status_code == 429, "rotating the forged prefix must not reset the bucket"
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert forged_address_response.status_code != 429, "the forged bucket must be untouched"


@pytest.mark.integration
async def test_b7_a_request_arriving_directly_is_keyed_on_its_peer_address(
    rate_limit_redis_url: str,
    build_rate_limit_app: RateLimitAppFactory,
    open_rate_limited_client: RateLimitClientFactory,
) -> None:
    """Uvicorn ignores the header from an untrusted peer, so the socket decides the bucket."""
    application = build_rate_limit_app(rate_limit_redis_url)
    proxied_application = ProxyHeadersMiddleware(application, trusted_hosts=PROXY_ADDRESS)
    forged_headers = build_forwarded_headers(FORGED_ADDRESS)

    async with open_rate_limited_client(
        application, DIRECT_CLIENT_ADDRESS, proxied_application
    ) as direct_client:
        allowed = [
            await direct_client.post(AUTH_PATH, headers=forged_headers)
            for _ in range(AUTH_REQUEST_LIMIT)
        ]
        rejected = await direct_client.post(AUTH_PATH, headers=forged_headers)

    async with open_rate_limited_client(
        application, OTHER_DIRECT_CLIENT_ADDRESS, proxied_application
    ) as other_direct_client:
        other_peer_response = await other_direct_client.post(AUTH_PATH, headers=forged_headers)

    async with open_rate_limited_client(
        application, PROXY_ADDRESS, proxied_application
    ) as proxied_client:
        forged_address_response = await proxied_client.post(AUTH_PATH, headers=forged_headers)

    assert all(response.status_code != 429 for response in allowed)
    assert rejected.status_code == 429
    assert rejected.json() == RATE_LIMIT_EXCEEDED_ENVELOPE
    assert other_peer_response.status_code != 429, "a different peer is a different bucket"
    assert forged_address_response.status_code != 429, "the forged bucket must be untouched"
