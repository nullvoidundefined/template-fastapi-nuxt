"""A cross-origin response must expose the headers a browser is otherwise forbidden to read.

`app.main` passes `EXPOSED_CORS_HEADERS` to `CORSMiddleware`, and until this module existed
nothing observed the result: a regression that dropped the `expose_headers` argument, or dropped
one name from the list, changed no test. A browser can read only the headers a response names in
`Access-Control-Expose-Headers`, so losing `Retry-After` makes a 429 unactionable for exactly the
cross-origin clients `CORS_ORIGIN` exists to serve, and losing `X-Request-Id` leaves a user with
no identifier to report a failure by.

Two things make these assertions real rather than decorative. The request carries an `Origin`
header matching the configured `cors_origin`, because Starlette's CORSMiddleware writes no CORS
response header at all for an origin it does not allow, so a same-origin request would pass
against an application that exposes nothing. And the expected names are written here as literals
rather than imported from `app.main`: iterating the constant under test would assert it equals
itself and would still pass after a name was deleted from it. Changing `EXPOSED_CORS_HEADERS`
therefore means changing this module in the same commit (R-513), which is the point.
"""

import httpx
import pytest

from tests.conftest import ApiClientFactory, ServerAppFactory

ALLOWED_ORIGIN = "https://client.example"
DISALLOWED_ORIGIN = "https://other.example"
ALLOW_ORIGIN_HEADER = "Access-Control-Allow-Origin"
EXPOSE_HEADERS_HEADER = "Access-Control-Expose-Headers"
# The literal names the application promises a cross-origin browser it may read. Written out
# rather than imported for the reason in the module docstring.
BROWSER_READABLE_HEADERS = ("Retry-After", "X-Request-Id")


def parse_exposed_headers(response: httpx.Response) -> set[str]:
    """Return the exposed header names, case-folded, from the response's exposure header.

    Parsed as the comma-separated list the header grammar defines rather than compared as one
    string, so the assertions do not depend on the order the middleware happens to join the names
    in, and case-folded because a header name is case-insensitive.
    """
    raw_value = response.headers.get(EXPOSE_HEADERS_HEADER, "")
    return {name.strip().casefold() for name in raw_value.split(",") if name.strip()}


async def test_cross_origin_response_exposes_every_header_a_browser_must_read(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure means a cross-origin browser cannot read `Retry-After` or `X-Request-Id`.

    Either the `expose_headers` argument has been dropped from the CORSMiddleware registration in
    `app.main.register_middleware`, or a name has been removed from `EXPOSED_CORS_HEADERS`. The
    `Access-Control-Allow-Origin` assertion is the control: it proves the middleware ran and
    accepted this origin, so an empty exposure header below is a real omission rather than the
    silence CORSMiddleware keeps for a request it never recognized as cross-origin.
    """
    monkeypatch.setenv("CORS_ORIGIN", ALLOWED_ORIGIN)
    application = build_server_app()

    async with build_api_client(application) as client:
        response = await client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers.get(ALLOW_ORIGIN_HEADER) == ALLOWED_ORIGIN
    exposed_header_names = parse_exposed_headers(response)
    assert exposed_header_names, f"{EXPOSE_HEADERS_HEADER} was absent or empty"
    for header_name in BROWSER_READABLE_HEADERS:
        assert header_name.casefold() in exposed_header_names, (
            f"{header_name} is no longer exposed to a cross-origin client; "
            f"the response exposed {sorted(exposed_header_names)}"
        )


async def test_a_same_origin_response_names_no_exposed_headers(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure means something other than CORS is writing the exposure header.

    This is what makes the test above discriminate rather than merely pass. CORSMiddleware
    returns early for a request carrying no `Origin` header and writes no CORS header at all, so
    an exposure header appearing here would mean the earlier assertions could be satisfied by a
    response decorated somewhere else entirely, with the CORSMiddleware registration removed. It
    is also the reason the test above has to send an `Origin`: this request reaches the same
    route and the same middleware chain, and gets nothing.
    """
    monkeypatch.setenv("CORS_ORIGIN", ALLOWED_ORIGIN)
    application = build_server_app()

    async with build_api_client(application) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert ALLOW_ORIGIN_HEADER not in response.headers
    assert EXPOSE_HEADERS_HEADER not in response.headers


async def test_a_disallowed_origin_is_never_granted_access_to_the_response(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure means an unconfigured origin can read the response body, not just its headers.

    The assertion is on `Access-Control-Allow-Origin` rather than on the exposure header because
    of how CORSMiddleware is built: it applies its fixed header set, the exposure list included,
    to every request carrying an `Origin`, and gates only the mirrored origin on the allowlist. A
    browser refusing the response for the missing `Access-Control-Allow-Origin` never consults
    the exposure list, so asserting that list were absent here would pin Starlette's internals
    instead of the behavior that matters, which is that this origin reads nothing.
    """
    monkeypatch.setenv("CORS_ORIGIN", ALLOWED_ORIGIN)
    application = build_server_app()

    async with build_api_client(application) as client:
        response = await client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert ALLOW_ORIGIN_HEADER not in response.headers
