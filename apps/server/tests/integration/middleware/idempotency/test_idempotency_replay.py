"""B-17: a repeated `POST` with the same key from the same user replays without running again.

The handler answers with its own call number, so a replay is recognizable by content as well as
by the probe's count: a second run would answer `call: 2`. Everything the middleware must leave
alone is pinned beside it: a request without a key, an anonymous request, a second user who
happens to pick the same key, and a key older than the twenty-four hour window.
"""

from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from tests.integration.middleware.idempotency.conftest import (
    ECHO_PATH,
    HandlerProbe,
    IdempotencyDatabase,
    build_request_headers,
    build_unique_key,
    encode_body,
    hash_body,
)


@pytest.mark.integration
async def test_b17_a_repeated_post_replays_the_stored_status_and_body(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """The second request gets the first response and the handler runs once."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "first"})

    async with idempotency_app as client:
        first = await client.post(ECHO_PATH, content=body, headers=build_request_headers(user, key))
        second = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json() == {"data": {"call": 1, "body": {"item": "first"}}}
    assert handler_probe.calls == 1
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
    assert claim.status_code == 201
    assert claim.response_body == first.json()
    assert claim.request_method == "POST"
    assert claim.request_path == ECHO_PATH
    assert claim.request_body_hash == hash_body(body)


@pytest.mark.integration
async def test_b17_the_same_key_from_another_user_runs_separately(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """Keys are scoped per user, so one user's key can never replay into another's request."""
    first_user = await idempotency_db.sign_in_user("first")
    second_user = await idempotency_db.sign_in_user("second")
    key = build_unique_key()
    body = encode_body({"item": "shared"})

    async with idempotency_app as client:
        first = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(first_user, key)
        )
        second = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(second_user, key)
        )

    assert first.json()["data"]["call"] == 1
    assert second.json()["data"]["call"] == 2
    assert handler_probe.calls == 2
    assert (await idempotency_db.read_claim(key, second_user.id)) is not None


@pytest.mark.integration
async def test_b17_a_request_without_a_key_runs_every_time(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """No header, no idempotency: the middleware passes the request straight through."""
    user = await idempotency_db.sign_in_user()
    body = encode_body({"item": "unkeyed"})
    await idempotency_db.assert_table_exists()

    async with idempotency_app as client:
        for _ in range(2):
            response = await client.post(
                ECHO_PATH, content=body, headers=build_request_headers(user, None)
            )
            assert response.status_code == 201

    assert handler_probe.calls == 2


@pytest.mark.integration
async def test_b17_an_anonymous_request_with_a_key_is_not_recorded(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """Only an authenticated request claims a key; an anonymous one runs and stores nothing."""
    key = build_unique_key()
    body = encode_body({"item": "anonymous"})
    await idempotency_db.assert_table_exists()
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "Idempotency-Key": key,
    }

    async with idempotency_app as client:
        first = await client.post(ECHO_PATH, content=body, headers=headers)
        second = await client.post(ECHO_PATH, content=body, headers=headers)

    assert first.json()["data"]["call"] == 1
    assert second.json()["data"]["call"] == 2


@pytest.mark.integration
async def test_b17_a_completed_key_older_than_24_hours_runs_again(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """The replay window is twenty-four hours; after it, the key is claimed afresh."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "stale"})

    async with idempotency_app as client:
        first = await client.post(ECHO_PATH, content=body, headers=build_request_headers(user, key))
        await idempotency_db.age_past_replay_window(key, user.id)
        second = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.json()["data"]["call"] == 1
    assert second.json()["data"]["call"] == 2
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.response_body == second.json()
