"""B-40: a key reused for a different method, path, or body answers 422 and runs nothing.

The claim binds a key to one request, so a key sent to one endpoint can never replay that
endpoint's response into another. The mismatch is refused whatever state the stored claim is in:
completed, held under a live lease, or abandoned with an expired lease, which a mismatched request
must never take over. A malformed key is refused before anything is stored (R-406).
"""

import pytest

from tests.integration.middleware.idempotency.conftest import (
    ECHO_PATH,
    OTHER_PATH,
    build_request_headers,
    build_unique_key,
    encode_body,
)

REUSED_CODE = "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.integration
@pytest.mark.parametrize(
    "reused_request",
    [
        ("POST", ECHO_PATH, {"item": "different"}),
        ("POST", OTHER_PATH, {"item": "original"}),
        ("PUT", ECHO_PATH, {"item": "original"}),
    ],
    ids=["body", "path", "method"],
)
async def test_b40_reusing_a_completed_key_for_another_request_answers_422(
    idempotency_app, idempotency_db, handler_probe, reused_request
) -> None:
    """Only the first request runs; the mismatched one gets the registry code and no replay."""
    method, path, payload = reused_request
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()

    async with idempotency_app as client:
        first = await client.post(
            ECHO_PATH,
            content=encode_body({"item": "original"}),
            headers=build_request_headers(user, key),
        )
        reused = await client.request(
            method, path, content=encode_body(payload), headers=build_request_headers(user, key)
        )

    assert first.status_code == 201
    assert reused.status_code == 422, reused.text
    assert reused.json()["code"] == REUSED_CODE
    assert handler_probe.calls == 1
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.response_body == first.json()


@pytest.mark.integration
@pytest.mark.parametrize("lease_seconds", [60, -1], ids=["live-lease", "expired-lease"])
async def test_b40_a_mismatched_request_never_waits_on_or_takes_over_an_in_progress_claim(
    idempotency_app, idempotency_db, handler_probe, lease_seconds
) -> None:
    """A different body meets someone else's claim: 422, not 409, and never a takeover."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    original_token = await idempotency_db.seed_claim(
        key, user.id, ECHO_PATH, encode_body({"item": "original"}), lease_seconds=lease_seconds
    )

    async with idempotency_app as client:
        reused = await client.post(
            ECHO_PATH,
            content=encode_body({"item": "different"}),
            headers=build_request_headers(user, key),
        )

    assert reused.status_code == 422, reused.text
    assert reused.json()["code"] == REUSED_CODE
    assert handler_probe.calls == 0
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.claim_token == original_token
    assert claim.state == "in_progress"


@pytest.mark.integration
@pytest.mark.parametrize("key", ["k" * 256, "has space", "café"], ids=["long", "space", "utf8"])
async def test_b40_a_malformed_key_answers_400_and_stores_nothing(
    idempotency_app, idempotency_db, handler_probe, key
) -> None:
    """R-406: an oversized or unprintable key is a validation error, not a claim."""
    user = await idempotency_db.sign_in_user()
    await idempotency_db.assert_table_exists()
    headers = build_request_headers(user, None)
    headers_with_key = [*headers.items(), ("Idempotency-Key", key.encode())]

    async with idempotency_app as client:
        response = await client.post(
            ECHO_PATH, content=encode_body({"item": "x"}), headers=headers_with_key
        )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert handler_probe.calls == 0
