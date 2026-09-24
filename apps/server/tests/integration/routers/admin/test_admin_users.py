"""B-19, backend half: `GET /v1/admin/users` behind `require_admin`.

A member is refused with 403 `AUTH_ADMIN_REQUIRED`, a request with no session with 401, and an
admin receives `{ data, meta: { total, limit, offset } }` whose items carry exactly `id`, `email`,
`role`, and `created_at`. The exact key set is asserted rather than the presence of a few keys,
because the failure this guards against is an extra key, the password hash above all.

`total` is compared with a count taken on the test's own connection at the same moment, since the
integration database holds whatever users other tests have committed.
"""

import uuid

import pytest
from sqlalchemy import text

ADMIN_USERS_PATH = "/v1/admin/users"
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
USER_ITEM_KEYS = {"id", "email", "role", "created_at"}
DEFAULT_PAGE_LIMIT = 20
COUNT_USERS_SQL = text("SELECT count(*) FROM users")


async def seed_signed_in_user(auth_db, email: str, is_admin: bool = False) -> tuple[uuid.UUID, str]:
    """Commit a user and a live session for it, optionally as an admin; return the id and token."""
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    if is_admin:
        await auth_db.promote_to_admin(user_id)
    raw_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, raw_token)
    return user_id, raw_token


async def count_users(auth_db) -> int:
    """Return how many users the database holds right now."""
    async with auth_db.engine.connect() as connection:
        return int(await connection.scalar(COUNT_USERS_SQL))


@pytest.mark.integration
async def test_b19_a_member_is_refused_with_auth_admin_required(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """A signed-in member gets 403 and the registry code, and no user data at all."""
    _user_id, raw_token = await seed_signed_in_user(auth_db, auth_emails("member"))

    response = await auth_client.get(ADMIN_USERS_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "AUTH_ADMIN_REQUIRED"
    assert set(response.json()) == {"code", "error"}


@pytest.mark.integration
async def test_b19_a_request_without_a_session_answers_auth_required(auth_client) -> None:
    """No cookie is a 401, not a 403: the caller is unknown rather than unprivileged."""
    response = await auth_client.get(ADMIN_USERS_PATH)

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.integration
async def test_b19_an_admin_receives_the_page_with_exactly_four_keys_per_user(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """The envelope, the default page, and the exact item shape, with no hash anywhere."""
    admin_email = auth_emails("admin")
    admin_id, raw_token = await seed_signed_in_user(auth_db, admin_email, is_admin=True)
    expected_total = await count_users(auth_db)

    response = await auth_client.get(
        ADMIN_USERS_PATH, params={"limit": 100}, headers=cookies.header(raw_token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["meta"] == {"total": expected_total, "limit": 100, "offset": 0}
    assert body["data"], "the admin itself is a user, so the page cannot be empty"
    assert all(set(item) == USER_ITEM_KEYS for item in body["data"])
    stored_hash = (await auth_db.read_users(admin_email))[0].password_hash
    assert stored_hash not in response.text
    assert "password" not in response.text
    if expected_total <= 100:
        admin_items = [item for item in body["data"] if item["id"] == str(admin_id)]
        assert admin_items == [
            {
                "id": str(admin_id),
                "email": admin_email,
                "role": "admin",
                "created_at": admin_items[0]["created_at"],
            }
        ]


@pytest.mark.integration
async def test_b19_the_default_page_is_twenty_from_offset_zero(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """Without parameters the meta echoes the defaults the route applied."""
    _admin_id, raw_token = await seed_signed_in_user(auth_db, auth_emails("admin"), is_admin=True)

    response = await auth_client.get(ADMIN_USERS_PATH, headers=cookies.header(raw_token))

    assert response.status_code == 200, response.text
    meta = response.json()["meta"]
    assert meta["limit"] == DEFAULT_PAGE_LIMIT
    assert meta["offset"] == 0
    assert len(response.json()["data"]) == min(DEFAULT_PAGE_LIMIT, meta["total"])


@pytest.mark.integration
async def test_b19_limit_and_offset_page_through_users_in_a_stable_order(
    auth_client, auth_emails, auth_db, cookies
) -> None:
    """Two one-item pages are two different users, and together they equal the two-item page."""
    _admin_id, raw_token = await seed_signed_in_user(auth_db, auth_emails("admin"), is_admin=True)
    await auth_db.seed_user(auth_emails("second"), VALID_PASSWORD)
    headers = cookies.header(raw_token)

    first = await auth_client.get(ADMIN_USERS_PATH, params={"limit": 1}, headers=headers)
    second = await auth_client.get(
        ADMIN_USERS_PATH, params={"limit": 1, "offset": 1}, headers=headers
    )
    both = await auth_client.get(ADMIN_USERS_PATH, params={"limit": 2}, headers=headers)

    assert first.json()["meta"] == {"total": first.json()["meta"]["total"], "limit": 1, "offset": 0}
    assert second.json()["meta"]["offset"] == 1
    assert len(first.json()["data"]) == 1
    assert len(second.json()["data"]) == 1
    assert first.json()["data"][0]["id"] != second.json()["data"][0]["id"]
    assert both.json()["data"] == [*first.json()["data"], *second.json()["data"]]


@pytest.mark.integration
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": "ten"},
        {"offset": "1; DROP TABLE users"},
        {"limit": "9" * 40},
        {"offset": "9" * 40},
    ],
)
async def test_b19_an_out_of_range_or_malformed_page_answers_400(
    auth_client, auth_emails, auth_db, cookies, params
) -> None:
    """R-406: a bad page parameter is the validation envelope, never a 500 and never a query."""
    _admin_id, raw_token = await seed_signed_in_user(auth_db, auth_emails("admin"), is_admin=True)

    response = await auth_client.get(
        ADMIN_USERS_PATH, params=params, headers=cookies.header(raw_token)
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
