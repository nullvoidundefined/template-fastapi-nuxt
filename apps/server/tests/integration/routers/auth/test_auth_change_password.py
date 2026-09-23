"""B-13: a password change proves the current password, then signs out every browser but this one.

Both halves are asserted, because they fail in opposite directions. A change that signs out
nobody leaves a stolen session alive, which is the case the feature exists for. A change that
signs out everybody logs the person out of the page they are standing on, which looks like a bug
to them and is the failure a hurried implementation produces.

Each browser here signs in through the endpoint, so the cookie a test later proves is dead is one
the browser stored and replayed, and each session is proven to authenticate before anything claims
it stopped.
"""

import hashlib

import bcrypt
import pytest

LOGIN_PATH = "/v1/auth/login"
ME_PATH = "/v1/auth/me"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
NEW_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))
WRONG_PASSWORD = "-".join(("not", "the", "current", "one"))


@pytest.mark.integration
async def test_b13_a_wrong_current_password_is_refused_and_changes_nothing(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-13: the stored hash, the old password, and the caller's session all survive a refusal."""
    email = auth_emails("guarded")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    signed_in = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD}
    )
    assert signed_in.status_code == 200, signed_in.text

    response = await auth_client.patch(
        ME_PATH, json={"current_password": WRONG_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    stored_hash = (await auth_db.read_users(email))[0].password_hash
    assert bcrypt.checkpw(VALID_PASSWORD.encode(), stored_hash.encode())
    assert not bcrypt.checkpw(NEW_PASSWORD.encode(), stored_hash.encode())
    assert (await auth_client.get(ME_PATH)).status_code == 200
    assert len(await auth_db.read_sessions(user_id)) == 1
    assert cookies.attributes(response) == {}


@pytest.mark.integration
async def test_b13_the_old_password_stops_working_and_the_new_one_works(
    auth_client, auth_emails, auth_db
) -> None:
    """B-13: the change takes effect on the next login, in both directions."""
    email = auth_emails("rotated")
    await auth_db.seed_user(email, VALID_PASSWORD)
    before = await auth_client.post(LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD})
    assert before.status_code == 200, before.text

    response = await auth_client.patch(
        ME_PATH, json={"current_password": VALID_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"id": before.json()["data"]["id"], "email": email}}
    with_old = await auth_client.post(LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD})
    assert with_old.status_code == 401, with_old.text
    assert with_old.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    with_new = await auth_client.post(LOGIN_PATH, json={"email": email, "password": NEW_PASSWORD})
    assert with_new.status_code == 200, with_new.text


@pytest.mark.integration
async def test_b13_the_other_browser_is_signed_out_and_the_caller_stays_signed_in(
    build_auth_app, open_auth_browsers, auth_emails, auth_db, cookies
) -> None:
    """B-13: exactly one session survives the change, and it is the one that asked for it."""
    email = auth_emails("two-browsers")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)

    async with open_auth_browsers(build_auth_app(), count=2) as browsers:
        changing, other_browser = browsers
        credentials = {"email": email, "password": VALID_PASSWORD}
        signed_in = await changing.post(LOGIN_PATH, json=credentials)
        assert signed_in.status_code == 200, signed_in.text
        assert (await other_browser.post(LOGIN_PATH, json=credentials)).status_code == 200
        assert (await changing.get(ME_PATH)).status_code == 200, "the caller must first be in"
        assert (await other_browser.get(ME_PATH)).status_code == 200, "the other must first be in"

        response = await changing.patch(
            ME_PATH, json={"current_password": VALID_PASSWORD, "new_password": NEW_PASSWORD}
        )

        assert response.status_code == 200, response.text
        signed_out = await other_browser.get(ME_PATH)
        still_signed_in = await changing.get(ME_PATH)

    assert signed_out.status_code == 401, signed_out.text
    assert still_signed_in.status_code == 200, still_signed_in.text
    surviving_token = cookies.attributes(signed_in)["value"]
    session_rows = await auth_db.read_sessions(user_id)
    assert [row.token_hash for row in session_rows] == [
        hashlib.sha256(surviving_token.encode()).hexdigest()
    ]
