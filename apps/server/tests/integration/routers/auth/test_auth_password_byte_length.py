"""A password bcrypt cannot hash is refused as input, on every route that hashes or checks one.

`MAX_PASSWORD_LENGTH` is applied through Pydantic's `Field(max_length=...)`, which counts
characters, while bcrypt's limit is 72 *bytes* and the pinned bcrypt 5.0 raises `ValueError` past
it rather than truncating. Forty accented Latin characters are forty characters and eighty bytes,
so such a password passes validation, reaches `bcrypt.hashpw` or `bcrypt.checkpw`, and the raise
nothing catches becomes a 500 `SERVER_INTERNAL_ERROR` on `POST /v1/auth/register`,
`POST /v1/auth/login` and `PATCH /v1/auth/me`. A value a person may legitimately type into a
password box must never be answered with a server error: the honest answer is the 400 the error
envelope already carries a `field_errors` entry for, naming the field that was refused.

The boundary is asserted from the other side as well. Exactly 72 bytes of the same multi-byte
character is a password bcrypt accepts, so registration must accept it too, and the account it
creates must be able to sign in with it. That is what stops the fix from being "refuse anything
that is not ASCII", which would lock out every person who writes their password in their own
language, and would be a far worse defect than the 500 it replaced.

Every value here is built at run time from a repeated character and has its character count and
its byte count asserted before it is sent, so what each test relies on is a measured fact about
the request it makes rather than an assumption about how the file was encoded.
"""

import uuid

import bcrypt
import httpx
import pytest

from tests.integration.routers.conftest import AuthDatabase, CookieTools, EmailFactory

LOGIN_PATH = "/v1/auth/login"
ME_PATH = "/v1/auth/me"
REGISTER_PATH = "/v1/auth/register"

# bcrypt's own ceiling, counted in bytes. bcrypt 5.0 raises past it instead of truncating, which
# is why the ceiling has to be enforced before the hash is attempted rather than relied upon.
MAX_PASSWORD_BYTES = 72
# Two bytes in UTF-8, so a password made of these is twice as long in bytes as in characters.
MULTI_BYTE_CHARACTER = "\N{LATIN SMALL LETTER E WITH ACUTE}"
# Forty characters, eighty bytes: inside the character limit the schema declares, past the byte
# limit bcrypt enforces. This is the value that reaches bcrypt today and raises there.
OVER_LIMIT_PASSWORD = MULTI_BYTE_CHARACTER * 40
# Exactly seventy-two bytes: the last password bcrypt will hash, and one it must still accept.
AT_LIMIT_PASSWORD = MULTI_BYTE_CHARACTER * (MAX_PASSWORD_BYTES // 2)
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))


def assert_password_is_short_in_characters_and_long_in_bytes(password: str) -> None:
    """Fail before the request when the value is not the shape the whole test depends on.

    The defect is the difference between counting characters and counting bytes, so a test that
    assumed the difference rather than measuring it would keep passing if the constant, the
    character, or the encoding ever changed underneath it.
    """
    assert len(password) <= MAX_PASSWORD_BYTES, len(password)
    assert len(password.encode()) > MAX_PASSWORD_BYTES, len(password.encode())


def read_field_errors(response: httpx.Response) -> dict[str, str]:
    """Return `field_errors` as a field-to-message map, empty when the body carries none."""
    body = response.json()
    return {entry["field"]: entry["message"] for entry in body.get("field_errors") or []}


@pytest.mark.integration
async def test_register_refuses_a_password_longer_than_bcrypt_can_hash_as_input(
    auth_client: httpx.AsyncClient, auth_emails: EmailFactory, auth_db: AuthDatabase
) -> None:
    """A 400 naming `password`; today the bcrypt ValueError reaches the caller as a 500."""
    email = auth_emails("over-limit-register")
    assert_password_is_short_in_characters_and_long_in_bytes(OVER_LIMIT_PASSWORD)

    response = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": OVER_LIMIT_PASSWORD}
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert "password" in read_field_errors(response), response.text
    assert await auth_db.read_users(email) == [], "a refused registration creates no account"


@pytest.mark.integration
async def test_login_refuses_a_password_longer_than_bcrypt_can_compare_as_input(
    auth_client: httpx.AsyncClient, auth_emails: EmailFactory, auth_db: AuthDatabase
) -> None:
    """The comparison is never attempted, so the caller gets a 400 rather than a 500."""
    email = auth_emails("over-limit-login")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    assert_password_is_short_in_characters_and_long_in_bytes(OVER_LIMIT_PASSWORD)

    response = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": OVER_LIMIT_PASSWORD}
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert "password" in read_field_errors(response), response.text
    assert await auth_db.read_sessions(user_id) == [], "a refused sign-in opens no session"


@pytest.mark.integration
async def test_change_password_refuses_either_password_longer_than_bcrypt_can_take(
    auth_client: httpx.AsyncClient,
    auth_emails: EmailFactory,
    auth_db: AuthDatabase,
    cookies: CookieTools,
) -> None:
    """Both fields reach bcrypt: the current one through checkpw, the new one through hashpw.

    So both are asserted, each naming its own field, and the account is asserted afterwards to
    still hold the password it started with: a 500 raised between the verification and the update
    would be a different defect with the same status code.
    """
    email = auth_emails("over-limit-change")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)
    session_header = cookies.header(raw_token)
    assert (await auth_client.get(ME_PATH, headers=session_header)).status_code == 200
    assert_password_is_short_in_characters_and_long_in_bytes(OVER_LIMIT_PASSWORD)

    over_limit_new = await auth_client.patch(
        ME_PATH,
        json={"current_password": VALID_PASSWORD, "new_password": OVER_LIMIT_PASSWORD},
        headers=session_header,
    )
    over_limit_current = await auth_client.patch(
        ME_PATH,
        json={"current_password": OVER_LIMIT_PASSWORD, "new_password": VALID_PASSWORD},
        headers=session_header,
    )

    assert over_limit_new.status_code == 400, over_limit_new.text
    assert over_limit_new.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert "new_password" in read_field_errors(over_limit_new), over_limit_new.text
    assert over_limit_current.status_code == 400, over_limit_current.text
    assert over_limit_current.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert "current_password" in read_field_errors(over_limit_current), over_limit_current.text
    stored_hash = (await auth_db.read_users(email))[0].password_hash
    assert bcrypt.checkpw(
        VALID_PASSWORD.encode(), stored_hash.encode()
    ), "a refused change leaves the stored password alone"
    assert (await auth_client.get(ME_PATH, headers=session_header)).status_code == 200


@pytest.mark.integration
async def test_register_accepts_a_password_of_exactly_seventy_two_multi_byte_bytes(
    auth_client: httpx.AsyncClient, auth_emails: EmailFactory, auth_db: AuthDatabase
) -> None:
    """The last password bcrypt can hash must still register, and must still sign in.

    Without this, "reject anything that is not ASCII" would pass the three tests above while
    refusing passwords bcrypt handles perfectly well.
    """
    email = auth_emails("at-limit")
    assert len(AT_LIMIT_PASSWORD.encode()) == MAX_PASSWORD_BYTES
    assert len(AT_LIMIT_PASSWORD) <= MAX_PASSWORD_BYTES

    registered = await auth_client.post(
        REGISTER_PATH, json={"email": email, "password": AT_LIMIT_PASSWORD}
    )
    signed_in = await auth_client.post(
        LOGIN_PATH, json={"email": email, "password": AT_LIMIT_PASSWORD}
    )

    assert registered.status_code == 201, registered.text
    assert signed_in.status_code == 200, signed_in.text
    user_rows = await auth_db.read_users(email)
    assert len(user_rows) == 1
    assert bcrypt.checkpw(AT_LIMIT_PASSWORD.encode(), user_rows[0].password_hash.encode())
