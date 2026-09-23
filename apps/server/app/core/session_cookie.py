"""Writes and clears the session cookie, in one place so five call sites cannot disagree.

Every attribute here is a defence rather than a preference. `httponly` keeps the token out of
reach of any script on the page, so a cross-site scripting bug cannot read a session. `samesite`
of lax means the browser withholds the cookie on a cross-site state-changing request, which is
the other half of what the CSRF guard enforces. `secure` keeps the cookie off plain HTTP, and is
absent only in local development, where there is no certificate to serve it under.

The lifetime is written once from `SESSION_TTL`, the same value the session row's `expires_at`
comes from, because a cookie that outlives its row is a request the server rejects for reasons
the browser cannot see.
"""

from fastapi import Response

from app.constants.session import SESSION_COOKIE_NAME, SESSION_TTL

LOCAL_DEVELOPMENT_ENVIRONMENT = "development"


def set_session_cookie(response: Response, raw_token: str, environment: str) -> None:
    """Write the session cookie for this environment, with the lifetime the row carries."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=environment != LOCAL_DEVELOPMENT_ENVIRONMENT,
        path="/",
    )


def clear_session_cookie(response: Response, environment: str) -> None:
    """Expire the session cookie, with the attributes it was written under.

    A browser replaces a cookie only when the name, path and domain match, so clearing has to use
    the same path the cookie was set with or the stale one survives alongside the expired reply.

    The header is written by hand rather than through `delete_cookie`, which serializes through
    `SimpleCookie` and quotes an empty value into `sid=""`. Two quote characters are a value under
    some parsers, so the cleared cookie is not reliably empty; an unquoted empty value is. Both
    `Max-Age` and `Expires` are sent, because a browser that ignores one honours the other.
    """
    attributes = [
        f"{SESSION_COOKIE_NAME}=",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
        "Path=/",
        "HttpOnly",
        "SameSite=lax",
    ]
    if environment != LOCAL_DEVELOPMENT_ENVIRONMENT:
        attributes.append("Secure")
    response.headers.append("set-cookie", "; ".join(attributes))
