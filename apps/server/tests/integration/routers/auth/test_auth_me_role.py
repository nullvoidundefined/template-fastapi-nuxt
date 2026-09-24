"""B-19: `GET /auth/me` now carries the user's role, read from the row rather than assumed.

The admin case is the one that matters. A route that answered a hard-coded `member` would pass
every member test in this directory, so an admin is seeded and must read back as `admin`.
Registration answers the same body shape, so a new account is shown to be a member there too.
"""

import uuid

import pytest

ME_PATH = "/v1/auth/me"
REGISTER_PATH = "/v1/auth/register"
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))


@pytest.mark.integration
async def test_b19_auth_me_answers_admin_for_an_admin(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """The role comes from the users row, so a promoted user reads back as an admin."""
    email = auth_emails("admin")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    await auth_db.promote_to_admin(user_id)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)

    response = await auth_client.get(ME_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 200, response.text
    assert response.json() == {"data": {"id": str(user_id), "email": email, "role": "admin"}}


@pytest.mark.integration
async def test_b19_a_new_registration_is_a_member(auth_client, auth_emails) -> None:
    """Registration can never create an admin, and its body says which role it did create."""
    email = auth_emails("register")

    response = await auth_client.post(
        REGISTER_PATH, json=dict([("email", email), ("password", VALID_PASSWORD)])
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"].get("role") == "member"
    assert response.json()["data"]["email"] == email
