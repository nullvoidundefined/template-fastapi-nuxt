"""B-10 and B-38: what registration stores, what cookie it sets, and how it refuses a bad body.

Every assertion here is on something outside the handler: the row Postgres holds, the attributes
on the `Set-Cookie` header a browser would enforce, and the response envelope. The cookie
attributes are asserted one at a time rather than as one parsed cookie, because each is a separate
protection and a naive `response.set_cookie(name, token)` drops all four at once: the failure
should name the attribute that is missing rather than say that the cookie is wrong.

The bcrypt cost is read out of the stored hash rather than compared against the constant, so a
change to `BCRYPT_ROUNDS` that never reached a stored password still fails this file.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest

from app.constants.session import SESSION_TTL

REGISTER_PATH = "/v1/auth/register"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
OTHER_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))
EXPECTED_BCRYPT_COST = 12
BCRYPT_PREFIXES = frozenset({"2a", "2b", "2y"})
VALIDATION_MESSAGE_PREFIX = "The request body failed validation"


@pytest.mark.integration
async def test_b10_registration_stores_a_cost_12_bcrypt_hash_of_the_submitted_password(
    auth_client, auth_emails, auth_db
) -> None:
    """B-10: the stored password is a bcrypt hash of what was sent, whose cost field reads 12."""
    email = auth_emails("hash")

    response = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
    )

    assert response.status_code == 201, response.text
    user_rows = await auth_db.read_users(email)
    assert len(user_rows) == 1
    stored_hash = user_rows[0].password_hash
    assert stored_hash.split("$")[1] in BCRYPT_PREFIXES
    assert int(stored_hash.split("$")[2]) == EXPECTED_BCRYPT_COST
    assert bcrypt.checkpw(VALID_PASSWORD.encode(), stored_hash.encode())
    assert VALID_PASSWORD not in stored_hash


@pytest.mark.integration
async def test_b10_registration_stores_the_email_trimmed_and_lowercased(
    auth_client, auth_emails, auth_db
) -> None:
    """B-10: an address typed with padding and mixed case is stored in its folded form."""
    email = auth_emails("mixed")

    response = await auth_client.post(
        REGISTER_PATH, json={"email": f"  {email.upper()}  ", "password": VALID_PASSWORD}
    )

    assert response.status_code == 201, response.text
    user_rows = await auth_db.read_users(email)
    assert len(user_rows) == 1
    assert user_rows[0].email == email
    body = response.json()
    assert set(body) == {"data"}
    assert set(body["data"]) == {"id", "email", "role"}
    assert body["data"]["email"] == email
    assert uuid.UUID(body["data"]["id"]) == user_rows[0].id


@pytest.mark.integration
async def test_b10_the_session_cookie_carries_every_attribute_a_browser_must_enforce(
    auth_client, auth_emails, cookies
) -> None:
    """B-10: the cookie is HttpOnly, SameSite=Lax, path-wide, and lives exactly seven days."""
    email = auth_emails("cookie")

    response = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
    )

    assert response.status_code == 201, response.text
    attributes = cookies.attributes(response)
    assert attributes, "registration must set the session cookie"
    assert attributes["value"], "the session cookie must carry a token"
    assert "httponly" in attributes
    assert attributes["samesite"].lower() == "lax"
    assert attributes["path"] == "/"
    assert int(attributes["max-age"]) == int(SESSION_TTL.total_seconds())


@pytest.mark.integration
async def test_b10_the_issued_cookie_is_stored_only_as_its_sha256(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-10: the row holds the SHA-256 of the cookie's token, and expires when the cookie does."""
    email = auth_emails("token")

    response = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
    )

    assert response.status_code == 201, response.text
    raw_token = cookies.attributes(response)["value"]
    user_rows = await auth_db.read_users(email)
    session_rows = await auth_db.read_sessions(user_rows[0].id)
    assert len(session_rows) == 1
    assert session_rows[0].token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert session_rows[0].token_hash != raw_token
    remaining_lifetime = session_rows[0].expires_at - datetime.now(UTC)
    assert abs(remaining_lifetime - SESSION_TTL) < timedelta(minutes=5)


@pytest.mark.integration
async def test_b10_a_mixed_case_duplicate_is_refused_and_leaves_the_first_account_untouched(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """B-10: a duplicate differing only in case and padding answers 409 and changes nothing.

    The second attempt sends a different password on purpose. A handler that answered 409 after
    already writing the new hash would leave the first account unopenable, and a test asserting
    only on the status would not notice.
    """
    email = auth_emails("duplicate")
    first = await auth_client.post(REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD})
    assert first.status_code == 201, first.text

    second = await auth_client.post(
        REGISTER_PATH, json={"email": f"  {email.upper()}  ", "password": OTHER_PASSWORD}
    )

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "AUTH_EMAIL_ALREADY_REGISTERED"
    assert cookies.attributes(second) == {}, "a refused registration must set no session"
    user_rows = await auth_db.read_users(email)
    assert len(user_rows) == 1
    assert bcrypt.checkpw(VALID_PASSWORD.encode(), user_rows[0].password_hash.encode())
    assert len(await auth_db.read_sessions(user_rows[0].id)) == 1


@pytest.mark.integration
async def test_b10_the_session_cookie_is_secure_under_production(
    build_auth_app, open_auth_browsers, auth_emails, auth_redis_url, cookies
) -> None:
    """B-10: under the production setting the cookie is marked Secure, and still HttpOnly."""
    email = auth_emails("production")
    application = build_auth_app(
        environment="production", redis_url=auth_redis_url, tls_to_postgres=False
    )

    async with open_auth_browsers(application) as browsers:
        response = await browsers[0].post(
            REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
        )

    assert response.status_code == 201, response.text
    attributes = cookies.attributes(response)
    assert "secure" in attributes
    assert "httponly" in attributes


@pytest.mark.integration
async def test_b10_the_session_cookie_is_not_secure_under_local_development(
    build_auth_app, open_auth_browsers, auth_emails, cookies
) -> None:
    """B-10: local development serves plain HTTP, where a Secure cookie would never come back."""
    email = auth_emails("development")
    application = build_auth_app(environment="development")

    async with open_auth_browsers(application) as browsers:
        response = await browsers[0].post(
            REGISTER_PATH, json={"email": email, "password": VALID_PASSWORD}
        )

    assert response.status_code == 201, response.text
    attributes = cookies.attributes(response)
    assert "secure" not in attributes
    assert "httponly" in attributes


@pytest.mark.integration
async def test_b38_an_invalid_email_answers_a_structured_field_error_naming_the_field(
    auth_client, auth_db
) -> None:
    """B-38: the envelope carries `field_errors`, one entry naming `email`, beside the prose.

    The prose `error` string keeps the shape it already has, because it is what the existing
    handlers and their tests read. The structured list is additive, and it is what a form can bind
    to the input the person is looking at.
    """
    response = await auth_client.post(
        REGISTER_PATH, json={"email": "not-an-email", "password": VALID_PASSWORD}
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert set(body) == {"code", "error", "field_errors"}
    assert body["code"] == "INPUT_VALIDATION_ERROR"
    assert body["error"].startswith(VALIDATION_MESSAGE_PREFIX)
    assert "email" in body["error"]
    assert len(body["field_errors"]) == 1
    assert body["field_errors"][0]["field"] == "email"
    assert isinstance(body["field_errors"][0]["message"], str)
    assert body["field_errors"][0]["message"]
    assert await auth_db.read_users("not-an-email") == []


@pytest.mark.integration
async def test_b38_every_offending_field_is_named_once_and_carries_only_field_and_message(
    auth_client,
) -> None:
    """B-38: two bad inputs give two entries, each exactly `{ field, message }`."""
    response = await auth_client.post(REGISTER_PATH, json={"email": "not-an-email"})

    assert response.status_code == 400, response.text
    field_errors = response.json()["field_errors"]
    assert {entry["field"] for entry in field_errors} == {"email", "password"}
    assert len(field_errors) == 2
    assert {tuple(sorted(entry)) for entry in field_errors} == {("field", "message")}
    assert all(entry["message"] for entry in field_errors)
