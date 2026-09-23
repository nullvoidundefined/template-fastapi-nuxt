"""The two rate-limit buckets and the paths the stricter one covers (spec B-7).

Two buckets rather than one, because the threat they answer is different. The global bucket bounds
what any one client can cost the service. The auth bucket bounds credential guessing, which needs
a far lower ceiling than ordinary browsing and would be invisible inside a limit of one hundred.

The auth paths are written as the full mounted paths, including the `/v1` prefix the router adds.
A pattern written without it never matches the path the middleware sees, and the route is then
silently left on the global limit alone, which is the defect this spelling exists to prevent.
"""

GLOBAL_REQUEST_LIMIT = 100
AUTH_REQUEST_LIMIT = 10
RATE_LIMIT_WINDOW_SECONDS = 15 * 60

# Every method of these paths counts against the auth bucket, because every method of them is a
# credential-handling request.
AUTH_RATE_LIMITED_PATHS = frozenset(
    {
        "/v1/auth/login",
        "/v1/auth/register",
        "/v1/auth/forgot-password",
        "/v1/auth/reset-password",
    }
)
# A path whose methods differ. `GET /v1/auth/me` is what a signed-in page calls on every
# navigation and would exhaust a bucket of ten in normal use, so it counts only against the global
# bucket; `PATCH /v1/auth/me` verifies a password and belongs in the stricter one. Matching on the
# path alone would have to choose one answer for both, and the lenient answer leaves a bcrypt
# comparison reachable one hundred times a window.
AUTH_RATE_LIMITED_ROUTES = frozenset({("PATCH", "/v1/auth/me")})
