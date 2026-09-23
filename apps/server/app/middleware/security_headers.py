"""Adds the response hardening headers that every response carries, successes and rejections alike.

Registered above CORS and above every guard, so a 403 from the CSRF guard and a 500 from the
outermost handler are decorated exactly like a 200. A header set only on successful responses is
the usual mistake here, and it leaves the responses an attacker is most likely to provoke as the
undefended ones.

`Strict-Transport-Security` is production only. Sending it from development or from a test would
pin a browser to HTTPS for a hostname that serves plain HTTP, and `localhost` would then be
unreachable until the header's age expired or the operator cleared it by hand.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_TYPE_OPTIONS_HEADER = (b"x-content-type-options", b"nosniff")
# `strict-origin-when-cross-origin` sends the full URL to this origin, only the origin to another
# HTTPS origin, and nothing when the target downgrades to HTTP, so a path carrying an identifier
# never leaves the site.
REFERRER_POLICY_HEADER = (b"referrer-policy", b"strict-origin-when-cross-origin")
# Two years with subdomains, the value the preload lists require.
STRICT_TRANSPORT_SECURITY_HEADER = (
    b"strict-transport-security",
    b"max-age=63072000; includeSubDomains",
)
PRODUCTION_ENVIRONMENT = "production"


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that appends the hardening headers to every HTTP response."""

    def __init__(self, app: ASGIApp, environment: str) -> None:
        """Wrap the downstream app and fix the header set this environment sends."""
        self.app = app
        self.headers = build_security_headers(environment)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Append the headers to the response start message, leaving every other message alone."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, self._build_decorating_send(send))

    def _build_decorating_send(self, send: Send) -> Send:
        """Return a send that adds the headers as the response starts."""

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *self.headers]}
            await send(message)

        return send_with_security_headers


def build_security_headers(environment: str) -> list[tuple[bytes, bytes]]:
    """Return the headers for this environment, with HSTS only when it is production."""
    headers = [CONTENT_TYPE_OPTIONS_HEADER, REFERRER_POLICY_HEADER]
    if environment == PRODUCTION_ENVIRONMENT:
        headers.append(STRICT_TRANSPORT_SECURITY_HEADER)
    return headers
