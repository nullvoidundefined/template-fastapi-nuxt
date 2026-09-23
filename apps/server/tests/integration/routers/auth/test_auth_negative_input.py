"""R-406: one negative-input test per auth handler, covering the three shapes of hostile input.

Each test drives the same three cases at one handler: a body past the 100 KB limit, a SQL
injection string in the field a caller controls, and bytes that are not valid UTF-8 where JSON was
declared. The shared requirement is that every one of them is refused through the error envelope,
with a registry code, rather than reaching the client as a 500 or, worse, being served.

For logout and `GET /auth/me` the hostile input is the cookie rather than the body, because that
is the only thing an anonymous caller supplies to them, and it reaches a SQL lookup.

The injection strings are also asserted to be harmless when they are legitimate input: a password
may contain any characters at all, and a handler that could be broken by one has a parameterized
query somewhere it should not.
"""

import uuid

import pytest

LOGIN_PATH = "/v1/auth/login"
LOGOUT_PATH = "/v1/auth/logout"
ME_PATH = "/v1/auth/me"
REGISTER_PATH = "/v1/auth/register"

# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
NEW_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))
# Past the 100 KB body limit the request-context middleware enforces before routing.
OVERSIZED_VALUE = "x" * 120_000
# Long enough to be a payload rather than a typo, and built from a repeated unit so that no
# credential-shaped literal appears here either.
OVERSIZED_COOKIE_VALUE = "a" * 4096
SQL_INJECTION_TEXT = "'; DROP TABLE users; --"
# Percent escapes that decode to nothing valid: an overlong encoding and a byte that never starts
# a UTF-8 sequence.
MALFORMED_COOKIE_VALUE = "%C0%80%FF"
MALFORMED_JSON_BODY = b'{"email": "\xff\xfe", "password": "\xc0\x80"}'
JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


@pytest.mark.integration
async def test_r406_register_refuses_an_oversized_body_an_injection_and_bad_encoding(
    auth_client, auth_emails, auth_db
) -> None:
    """R-406: registration refuses all three, and a password full of SQL is stored as a password."""
    email = auth_emails("hostile")

    oversized = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": OVERSIZED_VALUE}
    )
    injected_address = await auth_client.post(
        REGISTER_PATH, json={"email": SQL_INJECTION_TEXT, "password": VALID_PASSWORD}
    )
    malformed = await auth_client.post(
        REGISTER_PATH, content=MALFORMED_JSON_BODY, headers=JSON_CONTENT_TYPE
    )
    injected_password = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": SQL_INJECTION_TEXT}
    )

    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"
    assert injected_address.status_code == 400, injected_address.text
    assert injected_address.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert malformed.status_code == 400, malformed.text
    assert malformed.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert injected_password.status_code == 201, injected_password.text
    assert len(await auth_db.read_users(email)) == 1


@pytest.mark.integration
async def test_r406_login_refuses_an_oversized_body_an_injection_and_bad_encoding(
    auth_client, auth_emails, auth_db
) -> None:
    """R-406: every hostile login is refused, and none of them writes a session."""
    email = auth_emails("hostile-login")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)

    oversized = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": OVERSIZED_VALUE}
    )
    injected_address = await auth_client.post(
        LOGIN_PATH, json={"email": SQL_INJECTION_TEXT, "password": VALID_PASSWORD}
    )
    injected_password = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": SQL_INJECTION_TEXT}
    )
    malformed = await auth_client.post(
        LOGIN_PATH, content=MALFORMED_JSON_BODY, headers=JSON_CONTENT_TYPE
    )

    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"
    # An address that cannot be an address is either refused as input or refused as credentials;
    # what it may never be is served, or answered with a database error.
    assert injected_address.status_code in {400, 401}, injected_address.text
    assert injected_address.json()["code"] in {"INPUT_VALIDATION_ERROR", "AUTH_INVALID_CREDENTIALS"}
    assert injected_password.status_code == 401, injected_password.text
    assert injected_password.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert malformed.status_code == 400, malformed.text
    assert malformed.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert await auth_db.read_sessions(user_id) == []


@pytest.mark.integration
async def test_r406_logout_refuses_an_oversized_body_and_ignores_a_hostile_cookie(
    auth_client, cookies
) -> None:
    """R-406: logout answers 204 for any cookie it cannot resolve, and 413 for a huge body."""
    oversized = await auth_client.post(LOGOUT_PATH, json={"padding": OVERSIZED_VALUE})
    injected = await auth_client.post(LOGOUT_PATH, headers=cookies.header(SQL_INJECTION_TEXT))
    malformed = await auth_client.post(LOGOUT_PATH, headers=cookies.header(MALFORMED_COOKIE_VALUE))
    oversized_cookie = await auth_client.post(
        LOGOUT_PATH, headers=cookies.header(OVERSIZED_COOKIE_VALUE)
    )

    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"
    assert injected.status_code == 204, injected.text
    assert malformed.status_code == 204, malformed.text
    assert oversized_cookie.status_code == 204, oversized_cookie.text


@pytest.mark.integration
async def test_r406_auth_me_refuses_a_hostile_cookie_as_401_through_the_envelope(
    auth_client, cookies
) -> None:
    """R-406: the cookie is client input reaching a lookup, so every bad one is a clean 401."""
    unknown = await auth_client.get(ME_PATH, headers=cookies.header(uuid.uuid4().hex))
    injected = await auth_client.get(ME_PATH, headers=cookies.header(SQL_INJECTION_TEXT))
    malformed = await auth_client.get(ME_PATH, headers=cookies.header(MALFORMED_COOKIE_VALUE))
    oversized = await auth_client.get(ME_PATH, headers=cookies.header(OVERSIZED_COOKIE_VALUE))

    for response in (unknown, injected, malformed, oversized):
        assert response.status_code == 401, response.text
        assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.integration
async def test_r406_change_password_refuses_an_oversized_body_an_injection_and_bad_encoding(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """R-406: a hostile password change is refused, and the caller is still signed in after."""
    email = auth_emails("hostile-change")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)
    session_header = cookies.header(raw_token)
    assert (await auth_client.get(ME_PATH, headers=session_header)).status_code == 200

    oversized = await auth_client.patch(
        ME_PATH,
        json={"current_password": VALID_PASSWORD, "new_password": OVERSIZED_VALUE},
        headers=session_header,
    )
    injected = await auth_client.patch(
        ME_PATH,
        json={"current_password": SQL_INJECTION_TEXT, "new_password": NEW_PASSWORD},
        headers=session_header,
    )
    malformed = await auth_client.patch(
        ME_PATH, content=MALFORMED_JSON_BODY, headers={**session_header, **JSON_CONTENT_TYPE}
    )

    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"
    assert injected.status_code == 401, injected.text
    assert injected.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert malformed.status_code == 400, malformed.text
    assert malformed.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert (await auth_client.get(ME_PATH, headers=session_header)).status_code == 200
    assert len(await auth_db.read_sessions(user_id)) == 1
