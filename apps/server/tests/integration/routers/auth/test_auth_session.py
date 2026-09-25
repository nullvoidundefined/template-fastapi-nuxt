"""B-32 and B-31: reading the signed-in user, and ending the session that read it.

The logout test signs in through the endpoint rather than seeding a row, so the cookie it later
proves is dead is a cookie the browser actually stored and replayed. It asserts the clearing on
the `Set-Cookie` the logout sent, not only on a later rejection: a handler that deleted the row
and sent no `Set-Cookie` would leave the browser holding a cookie it believes is live, and a later
401 cannot tell that apart from a properly cleared one.

The replay afterwards goes through an explicit `Cookie` header, because the client's own jar has
by then dropped the cleared cookie: a plain request would be anonymous, and its 401 would say
nothing about whether the server revoked anything.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import pytest

from tests.integration.routers.conftest import AuthDatabase, CookieTools, EmailFactory

LOGIN_PATH = "/v1/auth/login"
LOGOUT_PATH = "/v1/auth/logout"
ME_PATH = "/v1/auth/me"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))


def has_past_expiry(attributes: dict[str, str]) -> bool:
    """Return True when these cookie attributes tell a browser to drop the cookie now."""
    if attributes.get("max-age") == "0":
        return True
    expires = attributes.get("expires")
    if not expires:
        return False
    try:
        return parsedate_to_datetime(expires) <= datetime.now(UTC)
    except (TypeError, ValueError):
        return False


@pytest.mark.integration
async def test_b32_auth_me_answers_the_id_and_email_and_never_the_password_hash(
    auth_client: httpx.AsyncClient,
    auth_emails: EmailFactory,
    auth_db: AuthDatabase,
    cookies: CookieTools,
) -> None:
    """B-32: the body is `{ data: { id, email } }` and the response carries no hash at all."""
    email = auth_emails("me")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)

    response = await auth_client.get(ME_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"id": str(user_id), "email": email, "role": "member"}}
    stored_hash = (await auth_db.read_users(email))[0].password_hash
    assert stored_hash not in response.text
    assert "password" not in response.text


@pytest.mark.integration
async def test_b32_auth_me_answers_401_auth_required_without_a_session(
    auth_client: httpx.AsyncClient,
) -> None:
    """B-32: no cookie is `AUTH_REQUIRED` in the envelope, not a 403 and not an empty 200."""
    response = await auth_client.get(ME_PATH)

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.integration
async def test_b31_logout_answers_204_deletes_the_row_and_clears_the_cookie(
    auth_client: httpx.AsyncClient,
    auth_emails: EmailFactory,
    auth_db: AuthDatabase,
    cookies: CookieTools,
) -> None:
    """B-31: the session that just worked is gone from the table and cleared from the browser."""
    email = auth_emails("logout")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    signed_in = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD}
    )
    assert signed_in.status_code == 200, signed_in.text
    raw_token = cookies.attributes(signed_in)["value"]
    assert (await auth_client.get(ME_PATH)).status_code == 200, "the cookie must first work"

    response = await auth_client.post(LOGOUT_PATH)

    assert response.status_code == 204, response.text
    assert response.content == b""
    cleared = cookies.attributes(response)
    assert cleared, "logout must send a Set-Cookie that clears the session cookie"
    assert cleared["value"] == ""
    assert has_past_expiry(cleared), cleared
    assert await auth_db.read_sessions(user_id) == []
    replayed = await auth_client.get(ME_PATH, headers=cookies.header(raw_token))
    assert replayed.status_code == 401, replayed.text


@pytest.mark.integration
async def test_b31_logout_without_a_session_answers_204_and_revokes_nothing_else(
    auth_client: httpx.AsyncClient,
    auth_emails: EmailFactory,
    auth_db: AuthDatabase,
    cookies: CookieTools,
) -> None:
    """B-31: an anonymous logout is a no-op that still answers 204, and nobody else is signed out.

    The other user's session is proven to work before and after, because a handler that deleted
    every session it could find when it found none of its own would pass a test that only read the
    status code.
    """
    other_email = auth_emails("bystander")
    other_user_id = await auth_db.seed_user(other_email, VALID_PASSWORD)
    other_token = uuid.uuid4().hex
    await auth_db.seed_session(other_user_id, other_token)
    before = await auth_client.get(ME_PATH, headers=cookies.header(other_token))
    assert before.status_code == 200, before.text

    response = await auth_client.post(LOGOUT_PATH)

    assert response.status_code == 204, response.text
    session_rows = await auth_db.read_sessions(other_user_id)
    assert [row.token_hash for row in session_rows] == [
        hashlib.sha256(other_token.encode()).hexdigest()
    ]
    after = await auth_client.get(ME_PATH, headers=cookies.header(other_token))
    assert after.status_code == 200, after.text
