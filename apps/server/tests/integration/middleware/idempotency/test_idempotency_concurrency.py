"""B-44 and B-53: overlapping requests on one key, against real Postgres, with real overlap.

Every test here holds a handler open on an `asyncio.Event` while another request with the same key
arrives, so the claim the second request meets is one the first request committed and is still
working under, not a row left by a sequential call that already finished.

Sixty seconds are not waited out. A lease that has run out is produced by moving `locked_until`
into the past on the test's own connection, which is exactly the state a crashed or stalled
holder leaves once its lease lapses; the middleware judges the lease with the database's `now()`.

The last test needs the holder to release its claim at one precise instant: after the other
request has read the claim and decided to take it over, and before its takeover statement runs.
It wraps the middleware's takeover function to pause there, which is the only way to put that
interleaving on demand; everything either side of the pause is the real code against Postgres.
"""

import asyncio
import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.repositories.request_idempotency_keys import (
    IdempotentRequest,
)
from app.repositories.request_idempotency_keys import (
    take_over_idempotency_key as real_take_over_idempotency_key,
)
from tests.integration.middleware.idempotency.conftest import (
    ECHO_PATH,
    HOLD_TIMEOUT_SECONDS,
    HandlerProbe,
    IdempotencyDatabase,
    build_request_headers,
    build_unique_key,
    encode_body,
)

IN_PROGRESS_CODE = "IDEMPOTENCY_KEY_IN_PROGRESS"


@pytest.mark.integration
async def test_b44_two_simultaneous_posts_run_the_handler_once_one_success_one_409(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """The second arrives while the first holds its claim, and is refused rather than run."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "simultaneous"})
    headers = build_request_headers(user, key)
    handler_probe.hold(1)

    async with idempotency_app as client:
        first_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await handler_probe.wait_until_entered(1)
        second = await client.post(ECHO_PATH, content=body, headers=headers)
        handler_probe.release[1].set()
        first = await asyncio.wait_for(first_task, HOLD_TIMEOUT_SECONDS)
        replayed = await client.post(ECHO_PATH, content=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["code"] == IN_PROGRESS_CODE
    assert replayed.json() == first.json()
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_b44_a_claim_stranded_past_its_lease_is_taken_over_and_runs_once(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """A crashed process's claim does not strand the key: the next request takes it over."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "stranded"})
    crashed_token = await idempotency_db.seed_claim(key, user.id, ECHO_PATH, body, lease_seconds=-1)

    async with idempotency_app as client:
        response = await client.post(
            ECHO_PATH, content=body, headers=build_request_headers(user, key)
        )

    assert response.status_code == 201, response.text
    assert handler_probe.calls == 1
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
    assert claim.claim_token != crashed_token
    assert claim.response_body == response.json()


@pytest.mark.integration
async def test_b44_two_simultaneous_takeovers_of_a_stranded_claim_run_the_handler_once(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """Only one takeover can win the single UPDATE; the other meets a live lease and gets 409."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "contested"})
    headers = build_request_headers(user, key)
    await idempotency_db.seed_claim(key, user.id, ECHO_PATH, body, lease_seconds=-1)
    handler_probe.hold(1)

    async with idempotency_app as client:
        tasks = [
            asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
            for _ in range(2)
        ]
        await handler_probe.wait_until_entered(1)
        done, _pending = await asyncio.wait(
            tasks, timeout=HOLD_TIMEOUT_SECONDS / 2, return_when=asyncio.FIRST_COMPLETED
        )
        refused = next(iter(done)).result()
        handler_probe.release[1].set()
        responses = await asyncio.wait_for(asyncio.gather(*tasks), HOLD_TIMEOUT_SECONDS)

    assert refused.status_code == 409, refused.text
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert handler_probe.calls == 1


@pytest.mark.integration
async def test_b53_a_superseded_holders_late_completion_changes_nothing(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """After a takeover the stored response and the claim belong to the request that took over."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "late"})
    headers = build_request_headers(user, key)
    handler_probe.hold(1)

    async with idempotency_app as client:
        original_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await handler_probe.wait_until_entered(1)
        await idempotency_db.expire_lease(key, user.id)
        takeover = await client.post(ECHO_PATH, content=body, headers=headers)
        claim_after_takeover = await idempotency_db.read_claim(key, user.id)
        handler_probe.release[1].set()
        original = await asyncio.wait_for(original_task, HOLD_TIMEOUT_SECONDS)
        replayed = await client.post(ECHO_PATH, content=body, headers=headers)

    assert takeover.status_code == 201, takeover.text
    assert takeover.json()["data"]["call"] == 2
    assert original.json()["data"]["call"] == 1
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim_after_takeover is not None
    assert claim.claim_token == claim_after_takeover.claim_token
    assert claim.response_body == takeover.json()
    assert replayed.json() == takeover.json()
    assert handler_probe.calls == 2


@pytest.mark.integration
async def test_b53_a_superseded_holders_late_release_leaves_the_new_claim_in_place(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
) -> None:
    """The original fails after being taken over; its release must not delete the new claim."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "late-failure"})
    headers = build_request_headers(user, key)
    handler_probe.hold(1)
    handler_probe.hold(2)
    handler_probe.failing_calls.add(1)

    async with idempotency_app as client:
        original_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await handler_probe.wait_until_entered(1)
        await idempotency_db.expire_lease(key, user.id)
        takeover_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await handler_probe.wait_until_entered(2)
        taken_over = await idempotency_db.read_claim(key, user.id)
        handler_probe.release[1].set()
        original = await asyncio.wait_for(original_task, HOLD_TIMEOUT_SECONDS)
        claim_after_late_release = await idempotency_db.read_claim(key, user.id)
        handler_probe.release[2].set()
        takeover = await asyncio.wait_for(takeover_task, HOLD_TIMEOUT_SECONDS)

    assert original.status_code == 500
    assert taken_over is not None
    assert claim_after_late_release is not None
    assert claim_after_late_release.claim_token == taken_over.claim_token
    assert claim_after_late_release.state == "in_progress"
    assert takeover.status_code == 201, takeover.text
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
    assert claim.response_body == takeover.json()


@pytest.mark.integration
async def test_b53_a_release_between_lease_check_and_takeover_claims_afresh_and_runs_once(
    idempotency_app: AbstractAsyncContextManager[httpx.AsyncClient],
    idempotency_db: IdempotencyDatabase,
    handler_probe: HandlerProbe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The takeover finds the row gone, retries the claim insert once, and runs the handler."""
    import app.middleware.idempotency as idempotency_module  # noqa: PLC0415

    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    body = encode_body({"item": "released"})
    headers = build_request_headers(user, key)
    handler_probe.hold(1)
    handler_probe.failing_calls.add(1)
    at_takeover = asyncio.Event()
    holder_released = asyncio.Event()

    async def pause_before_take_over(
        connection: AsyncConnection, request: IdempotentRequest, claim_token: uuid.UUID
    ) -> datetime | None:
        """Stop between the lease check and the takeover until the holder has released."""
        at_takeover.set()
        await asyncio.wait_for(holder_released.wait(), HOLD_TIMEOUT_SECONDS)
        return await real_take_over_idempotency_key(connection, request, claim_token)

    monkeypatch.setattr(idempotency_module, "take_over_idempotency_key", pause_before_take_over)

    async with idempotency_app as client:
        holder_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await handler_probe.wait_until_entered(1)
        await idempotency_db.expire_lease(key, user.id)
        retry_task = asyncio.create_task(client.post(ECHO_PATH, content=body, headers=headers))
        await asyncio.wait_for(at_takeover.wait(), HOLD_TIMEOUT_SECONDS)
        handler_probe.release[1].set()
        holder = await asyncio.wait_for(holder_task, HOLD_TIMEOUT_SECONDS)
        assert (await idempotency_db.read_claim(key, user.id)) is None
        holder_released.set()
        retry = await asyncio.wait_for(retry_task, HOLD_TIMEOUT_SECONDS)

    assert holder.status_code == 500
    assert retry.status_code == 201, retry.text
    assert retry.json()["data"]["call"] == 2
    assert handler_probe.calls == 2
    claim = await idempotency_db.read_claim(key, user.id)
    assert claim is not None
    assert claim.state == "completed"
    assert isinstance(claim.claim_token, uuid.UUID)
