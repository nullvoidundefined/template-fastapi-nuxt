"""The race B-11 and B-13 meet in: one login and one password change, genuinely overlapping.

Neither criterion names this case, and a transaction around each flow separately does not close
it. A login can read the user, verify the old password, and be descheduled. The password change
can then commit its new hash and delete every other session. The login finally inserts its row,
and the account is left holding a live session built on the credentials the change existed to
retire. That is the one outcome this file refuses.

Making that interleaving happen on purpose is the whole design here, and sleeping would not do
it: a sleep tuned to lose the race today passes tomorrow on a faster machine, for no reason
anybody can see. Postgres's own lock graph is the barrier instead. A connection of the test's own
holds `SELECT ... FOR UPDATE` on the user's row; the password change starts and is waited for
until Postgres reports that backend blocked; the login starts and is waited for until Postgres
reports both requests stalled; and only then is the row released.

Two properties follow, and they are what make this test discriminating rather than merely slow.

Against the implementation the plan describes, both flows take the row lock before they verify
anything, so both queue behind the control lock and Postgres serializes them. Whichever runs
second sees the other's committed work: the login either inserts a session the change then
deletes, or reads the new hash under the lock and is refused. Only the caller's own session is
left either way.

Against an implementation with no row lock, the change still blocks, because its `UPDATE users`
needs a row lock the control conflicts with. The login does not block at all: an `INSERT INTO
user_sessions` takes only a key-share lock on the parent row, which Postgres grants against an
outstanding `FOR UPDATE`, and that was measured rather than assumed. What stalls the login
instead is its own password verification, which runs off the connection and leaves its backend
idle inside its transaction with the user lookup as its last statement. So the barrier waits for
exactly that, releases while the login is still verifying, and the change commits its new hash and
deletes the sessions it can see before the login inserts the one it built from the old password.
The surviving session is then the bug, and the last assertion in this file is what names it.

One Postgres detail the barrier depends on: `pg_stat_activity` is snapshotted per transaction, so
a poll inside the control's own transaction would answer with the same frozen picture forever.
`pg_stat_clear_snapshot()` before each read is what makes the next read current.

The counts are narrowed to this test's own backends by `application_name`, and that is not
cosmetic. `pg_stat_activity` shows every backend in the database, `migrated_database_url` is
session-scoped and shared, and the default test run is parallel (R-509), so another worker's
integration test waiting on a lock, or sitting idle in its transaction after a `SELECT`, would be
counted here. The barrier would then release before this test's own two requests had actually met,
and `observed_stalls == [1, 2]` would hold for the wrong reason or fail for no reason of this
test's making. The application under test therefore opens every connection under a name generated
for this run, and both counting queries match on it.
"""

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, NamedTuple

import bcrypt
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings import Settings
from tests.integration.routers.conftest import (
    AuthAppFactory,
    AuthDatabase,
    CookieTools,
    EmailFactory,
)

LOGIN_PATH = "/v1/auth/login"
ME_PATH = "/v1/auth/me"
# Built from parts rather than written as one literal, so no credential-shaped string appears in
# this source for a secret scanner to flag (R-108).
VALID_PASSWORD = "-".join(("correct", "horse", "battery", "staple"))
NEW_PASSWORD = "-".join(("another", "entirely", "different", "phrase"))

LOCK_USER_SQL = text("SELECT id FROM users WHERE id = :user_id FOR UPDATE")
CLOCK_SQL = text("SELECT clock_timestamp()")
# Without this, every later read in the control's transaction answers from the snapshot the first
# read took, and the barrier would either release immediately or never.
CLEAR_STATS_SNAPSHOT_SQL = text("SELECT pg_stat_clear_snapshot()")
# `application_name` is what keeps the count to this test's own backends: every other worker's
# integration test shares this database, and a backend of theirs blocked on a lock is
# indistinguishable here from one of these two requests.
COUNT_BLOCKED_SQL = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
    "AND application_name = :application_name "
    "AND wait_event_type = 'Lock'"
)
# A request is stalled when Postgres is making it wait for a lock, or when it is holding a
# transaction open with nothing running after a SELECT of its own, which is what verifying a
# password off the connection looks like from here. The `since` bound is what makes the second
# case belong to this request rather than to whatever the pooled connection last ran.
COUNT_STALLED_SQL = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
    "AND application_name = :application_name "
    "AND (wait_event_type = 'Lock' OR (state = 'idle in transaction' "
    "AND query_start > :since AND btrim(query) ILIKE 'SELECT%'))"
)
# Comfortably longer than the bcrypt comparisons that precede the stall, and comfortably shorter
# than the 10-second statement timeout the engine sets, which would otherwise cancel a blocked
# statement before the test released it.
STALL_DEADLINE_SECONDS = 3.0
POLL_SECONDS = 0.02


async def count_stalled_backends(
    connection: AsyncConnection, application_name: str, since: datetime | None
) -> int:
    """Return how many of this run's other backends are stalled, reading the view afresh."""
    await connection.execute(CLEAR_STATS_SNAPSHOT_SQL)
    if since is None:
        return int(
            await connection.scalar(COUNT_BLOCKED_SQL, {"application_name": application_name}) or 0
        )
    return int(
        await connection.scalar(
            COUNT_STALLED_SQL, {"application_name": application_name, "since": since}
        )
        or 0
    )


async def wait_for_stalled_backends(
    connection: AsyncConnection,
    expected: int,
    requests: list[asyncio.Task[httpx.Response]],
    application_name: str,
    since: datetime | None = None,
) -> int:
    """Poll until `expected` backends are stalled, and return the number last seen.

    It returns rather than raises, so a run in which the two requests never met is an assertion
    about the overlap rather than an error about a timeout. It also stops as soon as every request
    has finished, which is what happens while the endpoints do not exist yet.
    """
    deadline = time.monotonic() + STALL_DEADLINE_SECONDS
    stalled = await count_stalled_backends(connection, application_name, since)
    while stalled < expected and time.monotonic() < deadline:
        if all(request.done() for request in requests):
            break
        await asyncio.sleep(POLL_SECONDS)
        stalled = await count_stalled_backends(connection, application_name, since)
    return stalled


async def run_overlapping_requests(
    control: AsyncConnection,
    user_id: uuid.UUID,
    application_name: str,
    change_password: Callable[[], Coroutine[Any, Any, httpx.Response]],
    log_in: Callable[[], Coroutine[Any, Any, httpx.Response]],
) -> tuple[list[int], list[httpx.Response]]:
    """Hold the user's row, start both requests, and release once both have stalled on it.

    Returns the number of stalled backends observed after each request was started, and the two
    responses. It asserts nothing itself, so every path through it still awaits both requests and
    no task is left pending when a caller's assertion fails.
    """
    observed_stalls: list[int] = []
    requests: list[asyncio.Task[httpx.Response]] = []
    async with control.begin():
        await control.execute(LOCK_USER_SQL, {"user_id": user_id})
        requests.append(asyncio.create_task(change_password()))
        observed_stalls.append(
            await wait_for_stalled_backends(control, 1, requests, application_name)
        )
        since = await control.scalar(CLOCK_SQL)
        requests.append(asyncio.create_task(log_in()))
        observed_stalls.append(
            await wait_for_stalled_backends(control, 2, requests, application_name, since)
        )
    return observed_stalls, list(await asyncio.gather(*requests))


class LabelledApplication(NamedTuple):
    """The application under test and the name every connection it opens carries."""

    application: FastAPI
    application_name: str


@pytest.fixture
def labelled_application(
    build_auth_app: AuthAppFactory, monkeypatch: pytest.MonkeyPatch
) -> LabelledApplication:
    """Build the application with every connection it opens named for this test run.

    The name is generated per run rather than fixed, so two parallel workers running this file do
    not count each other's backends either. It is added to the engine's own connect arguments
    rather than replacing them, so the connect timeout and the statement timeout the application
    really runs with are still the ones under test; a fixture that rebuilt them would be asserting
    against an engine no deployed process ever uses.
    """
    application_name = f"auth-race-{uuid.uuid4().hex}"
    from app.db import engine as database_engine  # noqa: PLC0415

    build_connect_args = database_engine.build_connect_args

    def build_named_connect_args(settings: Settings) -> dict[str, Any]:
        """Return the engine's connect arguments with this run's application name added."""
        connect_args = build_connect_args(settings)
        connect_args["server_settings"] = {
            **connect_args["server_settings"],
            "application_name": application_name,
        }
        return connect_args

    monkeypatch.setattr(database_engine, "build_connect_args", build_named_connect_args)
    return LabelledApplication(build_auth_app(), application_name)


@pytest.mark.integration
async def test_a_login_racing_a_password_change_leaves_no_session_from_the_old_password(
    labelled_application: LabelledApplication,
    open_auth_browsers: Callable[..., AbstractAsyncContextManager[list[httpx.AsyncClient]]],
    auth_emails: EmailFactory,
    auth_db: AuthDatabase,
    cookies: CookieTools,
) -> None:
    """The change wins or the login does, and either way only the caller's session survives."""
    email = auth_emails("race")
    user_id = await auth_db.seed_user(email, VALID_PASSWORD)
    changer_token = uuid.uuid4().hex
    await auth_db.seed_session(user_id, changer_token)

    async with open_auth_browsers(labelled_application.application, count=2) as browsers:
        changing, signing_in = browsers
        first_check = await changing.get(ME_PATH, headers=cookies.header(changer_token))
        assert first_check.status_code == 200, first_check.text

        control = await auth_db.engine.connect()
        try:
            observed_stalls, responses = await run_overlapping_requests(
                control,
                user_id,
                labelled_application.application_name,
                lambda: changing.patch(
                    ME_PATH,
                    json={"current_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
                    headers=cookies.header(changer_token),
                ),
                lambda: signing_in.post(
                    LOGIN_PATH, json={"email": email, "password": VALID_PASSWORD}
                ),
            )
        finally:
            await control.close()
        change_response, login_response = responses

        assert observed_stalls == [1, 2], (
            "both requests must have been in flight on the same user row at once; "
            f"Postgres reported {observed_stalls} stalled backends"
        )
        assert change_response.status_code == 200, change_response.text
        # Either ordering is correct. The change ran second and revoked the session the login had
        # just made, or the login ran second, read the new hash under the lock, and was refused.
        assert login_response.status_code in {200, 401}, login_response.text
        # A login that lost the race carries no cookie at all, and one that won carries a session
        # the change then revoked, so whatever it ended up with must not authenticate now.
        issued_token = cookies.attributes(login_response).get("value") or uuid.uuid4().hex
        replayed = await signing_in.get(ME_PATH, headers=cookies.header(issued_token))
        assert replayed.status_code == 401, replayed.text

    stored_hash = (await auth_db.read_users(email))[0].password_hash
    assert bcrypt.checkpw(NEW_PASSWORD.encode(), stored_hash.encode())
    session_rows = await auth_db.read_sessions(user_id)
    assert [row.token_hash for row in session_rows] == [
        hashlib.sha256(changer_token.encode()).hexdigest()
    ], "only the session that asked for the change may survive it"
