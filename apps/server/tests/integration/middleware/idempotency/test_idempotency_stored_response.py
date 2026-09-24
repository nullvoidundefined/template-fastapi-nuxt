"""IAN-339: what a completed claim stores, and which responses are never keyed at all.

A replay has to be the response the client missed, so the middleware stores the raw body bytes,
the content type, and an allowlist of the handler's headers rather than only a JSON body and the
status line. A plain-text 201 is therefore stored and replayed like a JSON one instead of releasing
its key, which would have let the retry run the side effect a second time.

Two kinds of response are refused a key, because buffering them would cost memory without bound:
a streaming response, recognized by its missing Content-Length, and one larger than the stored
response cap. Both pass through to the client untouched, and both release their claim, so the
table holds nothing for them and a retry runs the handler again.

Set-Cookie is never stored or replayed. A claim row would otherwise hold a live session token in
clear text, where the sessions table keeps only its hash.
"""

import pytest

from tests.integration.middleware.idempotency.conftest import (
    CREATED_CACHE_CONTROL,
    CREATED_LOCATION,
    ECHO_PATH,
    HANDLER_COOKIE_NAME,
    HEADERS_PATH,
    MALFORMED_LENGTH_PATH,
    NO_CONTENT_PATH,
    OVERSIZED_PATH,
    PROBLEM_PATH,
    STREAM_PATH,
    SUPERSCRIPT_LENGTH_PATH,
    TEXT_PATH,
    UNDECLARED_OVERSIZED_PATH,
    UNLISTED_HEADER_NAME,
    build_request_headers,
    build_unique_key,
    encode_body,
)


@pytest.mark.integration
async def test_a_plain_text_response_is_stored_and_replayed_byte_for_byte(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """A non-JSON 201 completes its claim, and the retry gets the same bytes and content type."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "text"})

    async with idempotency_app as client:
        first = await client.post(TEXT_PATH, content=body, headers=build_request_headers(user, key))
        second = await client.post(
            TEXT_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201, first.text
    assert handler_probe.calls == 1
    assert second.status_code == 201
    assert second.content == first.content == b"created by call 1"
    assert second.headers.get("content-type") == first.headers.get("content-type")
    stored = await idempotency_db.read_stored_response(key, user.id)
    assert stored is not None
    assert bytes(stored.response_body_bytes) == b"created by call 1"
    assert stored.response_content_type == first.headers["content-type"]


@pytest.mark.integration
async def test_a_replay_carries_the_allowlisted_headers_and_never_a_cookie(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """Location and Cache-Control come back; Set-Cookie and an unlisted header do not."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "headers"})

    async with idempotency_app as client:
        first = await client.post(
            HEADERS_PATH, content=body, headers=build_request_headers(user, key)
        )
        second = await client.post(
            HEADERS_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201, first.text
    assert HANDLER_COOKIE_NAME in first.headers["set-cookie"]
    assert handler_probe.calls == 1
    assert second.json() == first.json()
    assert second.headers.get("location") == CREATED_LOCATION
    assert second.headers.get("cache-control") == CREATED_CACHE_CONTROL
    assert second.headers.get("content-encoding") == "identity"
    assert "set-cookie" not in second.headers
    assert UNLISTED_HEADER_NAME.lower() not in second.headers
    stored = await idempotency_db.read_stored_response(key, user.id)
    assert stored is not None
    stored_names = {name for name, _value in stored.response_headers}
    assert stored_names == {"location", "cache-control", "content-encoding"}


@pytest.mark.integration
async def test_a_streaming_response_is_passed_through_and_never_keyed(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """The stream reaches the client whole, no claim is kept, and the retry runs again."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "stream"})

    async with idempotency_app as client:
        first = await client.post(
            STREAM_PATH, content=body, headers=build_request_headers(user, key)
        )
        assert (await idempotency_db.read_claim(key, user.id)) is None
        second = await client.post(
            STREAM_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201
    assert first.json() == {"data": {"call": 1}}
    assert second.json() == {"data": {"call": 2}}
    assert handler_probe.calls == 2


@pytest.mark.integration
async def test_a_response_past_the_cap_is_passed_through_and_never_keyed(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """An oversized body reaches the client whole, no claim is kept, and the retry runs again."""
    from app.constants.idempotency import MAX_STORED_RESPONSE_BYTES  # noqa: PLC0415

    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "oversized"})

    async with idempotency_app as client:
        first = await client.post(
            OVERSIZED_PATH, content=body, headers=build_request_headers(user, key)
        )
        assert (await idempotency_db.read_claim(key, user.id)) is None
        second = await client.post(
            OVERSIZED_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201
    assert len(first.content) == MAX_STORED_RESPONSE_BYTES + 1
    assert first.json()["data"]["call"] == 1
    assert second.json()["data"]["call"] == 2
    assert handler_probe.calls == 2


@pytest.mark.integration
async def test_a_claim_completed_before_the_raw_body_columns_still_replays_its_json(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """A row revision 0005 wrote has only a JSONB body; it replays as JSON without running."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "legacy"})
    stored_body = {"data": {"call": 0, "body": {"item": "legacy"}}}
    await idempotency_db.seed_legacy_completed_claim(key, user.id, ECHO_PATH, body, stored_body)

    async with idempotency_app as client:
        replayed = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert replayed.status_code == 201
    assert replayed.json() == stored_body
    assert replayed.headers["content-type"] == "application/json"
    assert handler_probe.calls == 0


@pytest.mark.integration
async def test_a_body_past_the_cap_with_no_declared_length_is_never_keyed(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """The running total catches a body whose size no Content-Length announced."""
    from app.constants.idempotency import MAX_STORED_RESPONSE_BYTES  # noqa: PLC0415

    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "undeclared"})

    async with idempotency_app as client:
        first = await client.post(
            UNDECLARED_OVERSIZED_PATH, content=body, headers=build_request_headers(user, key)
        )
        assert (await idempotency_db.read_claim(key, user.id)) is None
        second = await client.post(
            UNDECLARED_OVERSIZED_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert len(first.content) == MAX_STORED_RESPONSE_BYTES + 1
    assert first.json()["data"]["call"] == 1
    assert second.json()["data"]["call"] == 2


@pytest.mark.integration
async def test_a_malformed_content_length_is_judged_by_the_body_and_still_replays(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """An unparseable length neither breaks the response nor loses the key."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "malformed"})

    async with idempotency_app as client:
        first = await client.post(
            MALFORMED_LENGTH_PATH, content=body, headers=build_request_headers(user, key)
        )
        second = await client.post(
            MALFORMED_LENGTH_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201
    assert first.json() == {"data": {"call": 1}}
    assert second.json() == first.json()
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_a_replayed_204_carries_no_content_length(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """RFC 9110 forbids Content-Length on a 204, so the replay sends none, as the handler did."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "no-content"})

    async with idempotency_app as client:
        first = await client.post(
            NO_CONTENT_PATH, content=body, headers=build_request_headers(user, key)
        )
        second = await client.post(
            NO_CONTENT_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == second.status_code == 204
    assert "content-length" not in first.headers
    assert "content-length" not in second.headers
    assert second.content == b""
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_a_suffixed_json_body_is_kept_in_the_column_older_replicas_read(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """An `application/problem+json` body is parsed into `response_body` like plain JSON."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "problem"})

    async with idempotency_app as client:
        first = await client.post(
            PROBLEM_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 422
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.response_body == {"title": "rejected", "call": 1}


@pytest.mark.integration
async def test_a_content_length_with_a_non_ascii_digit_is_judged_by_the_body(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """A length that `isdigit()` accepts but `int()` refuses is treated as undeclared too."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "superscript"})

    async with idempotency_app as client:
        first = await client.post(
            SUPERSCRIPT_LENGTH_PATH, content=body, headers=build_request_headers(user, key)
        )
        second = await client.post(
            SUPERSCRIPT_LENGTH_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201
    assert first.json() == {"data": {"call": 1}}
    assert second.json() == first.json()
    assert handler_probe.calls == 1
