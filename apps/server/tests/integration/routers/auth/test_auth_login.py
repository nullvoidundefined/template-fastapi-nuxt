"""B-11: what a login answers, what it writes, and what it tidies up on the way.

The two failure paths are asserted against each other rather than each against a constant, because
the property that matters is that they are indistinguishable: a client that can tell a wrong
password from an unknown address can enumerate which addresses have accounts.

The rate-limit test at the end is here rather than with the limiter's own tests because these two
paths are only now real routes. A limiter that counted a 404 and stopped counting once a handler
existed would still pass every test in `tests/unit/middleware`, and the auth bucket is the one
protection standing between this endpoint and an unbounded credential-guessing run.
"""

import hashlib
import uuid

import pytest

from app.constants.rate_limits import AUTH_REQUEST_LIMIT
from app.constants.session import SESSION_TTL

LOGIN_PATH = "/v1/auth/login"
ME_PATH = "/v1/auth/me"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
OTHER_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))


@pytest.mark.integration
async def test_b11_a_wrong_password_and_an_unknown_email_answer_exactly_the_same_thing(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-11: both failures answer 401 AUTH_INVALID_CREDENTIALS, byte for byte, and set no cookie."""
    known_email = auth_emails("known")
    await auth_db.seed_user(known_email, VALID_PASSWORD)

    wrong_password = await auth_client.post(
        LOGIN_PATH, json={"email": known_email, "password": OTHER_PASSWORD}
    )
    unknown_email = await auth_client.post(
        LOGIN_PATH, json={"email": auth_emails("nobody"), "password": VALID_PASSWORD}
    )

    assert wrong_password.status_code == 401, wrong_password.text
    assert unknown_email.status_code == wrong_password.status_code
    assert wrong_password.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert unknown_email.json() == wrong_password.json()
    assert cookies.attributes(wrong_password) == {}
    assert cookies.attributes(unknown_email) == {}


@pytest.mark.integration
async def test_b11_a_correct_login_writes_a_session_row_and_sets_the_same_cookie(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-11: the answer carries the user, and the cookie's token is stored only as its hash."""
    email = auth_emails("correct")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)

    response = await auth_client.post(LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD})

    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"id": str(user_id), "email": email, "role": "member"}}
    attributes = cookies.attributes(response)
    assert "httponly" in attributes
    assert attributes["samesite"].lower() == "lax"
    assert attributes["path"] == "/"
    assert int(attributes["max-age"]) == int(SESSION_TTL.total_seconds())
    session_rows = await auth_db.read_sessions(user_id)
    assert len(session_rows) == 1
    assert session_rows[0].token_hash == hashlib.sha256(attributes["value"].encode()).hexdigest()


@pytest.mark.integration
async def test_b11_a_login_removes_the_expired_session_and_leaves_the_live_one_working(
    build_auth_app, open_auth_browsers, auth_emails, auth_db, cookies
) -> None:
    """B-11: exactly the expired row goes, and the other browser is still signed in afterwards.

    Two browsers rather than one, because the assertion is about the session that belongs to the
    other browser: replaying its cookie from the jar that just received a new one would prove
    nothing about which of the two the server accepted.
    """
    email = auth_emails("expired")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    live_token = uuid.uuid4().hex
    stale_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, live_token)
    await auth_db.seed_session(user_id, stale_token, expired=True)

    async with open_auth_browsers(build_auth_app(), count=2) as browsers:
        signing_in, other_browser = browsers
        assert (
            await other_browser.get(ME_PATH, headers=cookies.header(live_token))
        ).status_code == 200
        response = await signing_in.post(
            LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD}
        )
        still_signed_in = await other_browser.get(ME_PATH, headers=cookies.header(live_token))

    assert response.status_code == 200, response.text
    session_rows = await auth_db.read_sessions(user_id)
    stored_hashes = {row.token_hash for row in session_rows}
    assert hashlib.sha256(stale_token.encode()).hexdigest() not in stored_hashes
    assert hashlib.sha256(live_token.encode()).hexdigest() in stored_hashes
    assert len(session_rows) == 2
    assert still_signed_in.status_code == 200, still_signed_in.text


@pytest.mark.integration
async def test_b11_a_mixed_case_whitespace_padded_address_logs_in(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-11: the address is folded on the way in, so the account is found however it was typed."""
    email = auth_emails("padded")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)

    response = await auth_client.post(
        LOGIN_PATH, json={"email": f"  {email.upper()}  ", "password": VALID_PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["id"] == str(user_id)
    assert cookies.attributes(response)["value"]
    assert len(await auth_db.read_sessions(user_id)) == 1


@pytest.mark.integration
async def test_b7_the_auth_bucket_counts_login_and_leaves_auth_me_outside_it(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-7: the eleventh login in the window is refused, while `/auth/me` keeps answering.

    `/v1/auth/me` is deliberately outside the auth bucket: a signed-in page calls it on every
    navigation and a bucket of ten would sign that person out in normal use. Asserting it here,
    after the bucket is already exhausted, is what makes that concrete.
    """
    email = auth_emails("limited")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)

    for attempt in range(AUTH_REQUEST_LIMIT):
        refused = await auth_client.post(
            LOGIN_PATH, json={"email": email, "password": OTHER_PASSWORD}
        )
        assert refused.status_code == 401, f"attempt {attempt}: {refused.text}"

    over_the_limit = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": OTHER_PASSWORD}
    )

    assert over_the_limit.status_code == 429, over_the_limit.text
    assert over_the_limit.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert over_the_limit.headers["Retry-After"]
    for _ in range(3):
        still_served = await auth_client.get(ME_PATH, headers=cookies.header(raw_token))
        assert still_served.status_code == 200, still_served.text
