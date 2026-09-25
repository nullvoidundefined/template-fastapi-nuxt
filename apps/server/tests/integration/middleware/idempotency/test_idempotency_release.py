"""B-18: a handler that fails releases its claim, so the client's retry runs instead of a 409.

Two kinds of failure are covered, because they reach the middleware differently: an exception
propagates through it, and a 5xx response passes through it as ordinary messages. Both must leave
no claim behind, and the retry must run the handler and be the response that is stored.
"""

from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from tests.integration.middleware.idempotency.conftest import (
    FLAKY_PATH,
    UNAVAILABLE_PATH,
    HandlerProbe,
    IdempotencyDatabase,
    build_request_headers,
    build_unique_key,
    encode_body,
)


@pytest.mark.integration
@pytest.mark.parametrize(("path", "failed_status"), [(FLAKY_PATH, 500), (UNAVAILABLE_PATH, 503)])
async def test_b18_a_failed_handler_releases_its_claim_and_the_retry_runs(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
    path: str,
    failed_status: int,
) -> None:
    """The failure leaves no row, the retry runs the handler, and the retry is what is stored."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"attempt": "same"})

    async with idempotency_app as client:
        failed = await client.post(path, content=body, headers=build_request_headers(user, key))
        assert failed.status_code == failed_status
        assert (await idempotency_db.read_claim(key, user.id)) is None
        retried = await client.post(path, content=body, headers=build_request_headers(user, key))
        replayed = await client.post(path, content=body, headers=build_request_headers(user, key))

    assert retried.status_code == 201, retried.text
    assert retried.json() == {"data": {"call": 2}}
    assert replayed.json() == retried.json()
    assert handler_probe.calls == 2
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
