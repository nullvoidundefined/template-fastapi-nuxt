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

# `/v1/auth/me` is deliberately absent: a signed-in page calls it on every navigation, so it would
# exhaust a bucket of ten in normal use. It still counts against the global bucket.
AUTH_RATE_LIMITED_PATHS = frozenset(
    {
        "/v1/auth/login",
        "/v1/auth/register",
        "/v1/auth/forgot-password",
        "/v1/auth/reset-password",
    }
)
