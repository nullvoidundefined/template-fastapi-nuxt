"""B-17 and B-18 at the edges of settlement: after the handler has answered.

The handler's own transaction has committed by the time the middleware stores the response, so a
claim that is neither completed nor released at that point is the dangerous state: once its lease
lapses, a retry takes it over and runs the side effect a second time. These tests break the two
ways the middleware can be interrupted there, a failed write and a cancellation, and assert the
claim still ends completed. The query-string case closes a gap in B-40's identity check.
"""

import asyncio

import pytest

import app.middleware.idempotency as idempotency_module
from tests.integration.middleware.idempotency.conftest import (
    ECHO_PATH,
    build_request_headers,
    build_unique_key,
    encode_body,
)

COMPLETE_FUNCTION_NAME = "complete_idempotency_key"


@pytest.mark.integration
async def test_b17_a_transient_failure_storing_the_response_is_retried_until_it_completes(
    idempotency_app, idempotency_db, handler_probe, monkeypatch
) -> None:
    """A dropped connection on the first completion write does not leave the claim open."""
    real_complete = getattr(idempotency_module, COMPLETE_FUNCTION_NAME)
    failures_left = [1]

    async def complete_after_one_failure(*args, **kwargs):
        if failures_left[0]:
            failures_left[0] -= 1
            raise OSError("connection reset while storing the response")
        return await real_complete(*args, **kwargs)

    monkeypatch.setattr(idempotency_module, COMPLETE_FUNCTION_NAME, complete_after_one_failure)
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()

    async with idempotency_app as client:
        first = await client.post(
            ECHO_PATH, content=encode_body({"n": 1}), headers=build_request_headers(user, key)
        )

    assert first.status_code == 201, first.text
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_b18_a_cancellation_while_storing_the_response_still_completes_the_claim(
    idempotency_app, idempotency_db, handler_probe, monkeypatch
) -> None:
    """A timeout that lands after the handler answered cannot strand the claim in progress."""
    real_complete = getattr(idempotency_module, COMPLETE_FUNCTION_NAME)
    completion_entered = asyncio.Event()
    completion_may_finish = asyncio.Event()

    async def slow_complete(*args, **kwargs):
        completion_entered.set()
        await completion_may_finish.wait()
        return await real_complete(*args, **kwargs)

    monkeypatch.setattr(idempotency_module, COMPLETE_FUNCTION_NAME, slow_complete)
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()

    async with idempotency_app as client:
        request_task = asyncio.create_task(
            client.post(
                ECHO_PATH, content=encode_body({"n": 1}), headers=build_request_headers(user, key)
            )
        )
        await asyncio.wait_for(completion_entered.wait(), timeout=10)
        request_task.cancel()
        completion_may_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await request_task
        for _ in range(100):
            claim = await idempotency_db.read_claim(key, user.id)
            if claim is not None and claim.state == "completed":
                break
            await asyncio.sleep(0.05)

    assert claim is not None
    assert claim.state == "completed"
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_b40_the_same_key_on_a_different_query_string_is_a_reuse(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """The query string is part of what the key promises, so a different one answers 422."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"n": 1})

    async with idempotency_app as client:
        first = await client.post(
            f"{ECHO_PATH}?account=a", content=body, headers=build_request_headers(user, key)
        )
        second = await client.post(
            f"{ECHO_PATH}?account=b", content=body, headers=build_request_headers(user, key)
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 422, second.text
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert handler_probe.calls == 1
