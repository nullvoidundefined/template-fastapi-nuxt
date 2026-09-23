# Slice 03, PR 1: user_sessions, the security primitives, and the session dependency

**Ticket:** IAN-315
**Branch:** `feat/slice03-sessions-and-security`
**Plan:** `docs/slices/slice-03-auth.md`, the PR 1 block
**Story:** US-AUTH-001

## Summary

No route reaches any of this yet, which is the point. Every endpoint in PR 2 needs the same four
things, and they are the part of the slice where a mistake is a security defect rather than a bug:
a session table, a way to hash and check a password that does not block the process or leak which
addresses have accounts, a token whose raw form lives only in the cookie, and a dependency that
turns that cookie into a user. Building them inside the first endpoint would mean the second
endpoint refactors them, and refactoring a timing property is how it stops being true.

## What changed

- **`migrations/versions/20260923_0002_create_user_sessions.py` and `app/db/tables.py`.** The table
  stores the SHA-256 of the token, cascades from the user, and indexes `expires_at`. No
  `set_updated_at` trigger: a session has no `updated_at`.
- **`app/core/security.py`.** `hash_password`, `verify_password`, `resolve_comparison_hash`,
  `generate_session_token`.
- **`app/repositories/users.py`.** `get_user_by_email` and `lock_user_for_update`, both normalizing
  the address.
- **`app/repositories/user_sessions.py`.** `create_session` and `touch_session`.
- **`app/dependencies/current_user.py`.** `get_current_user` and `resolve_current_user`.
- **`apps/server/pyproject.toml`.** bcrypt as a runtime dependency (R-331: nothing in the tree
  hashes a password, and the Python track names bcrypt specifically).

## Architectural decisions

**`verify_password` has no conditional at all.** Chosen: resolve a comparison hash through a
separate pure function, compare once, return the conjunction. Alternative: branch on whether the
user exists. Why: B-11 requires that an unknown email costs what a wrong password costs, or the
difference enumerates which addresses have accounts. A branch inside the verifier is exactly where
a short-circuit creeps back in during a later edit, and the plan's first draft tried to catch that
with a value assertion, which does not: an implementation that returns `False` the moment the
stored hash is missing passes "the dummy password is rejected" while never running bcrypt at all.
Codex raised this while authoring the tests. The answer is structural rather than observational,
because R-401 rules out asserting on a recorded call: the choice lives in
`resolve_comparison_hash`, which a test asserts directly, and an AST test pins that the verifier
has one return, one await, no conditionals, and compares the thing the resolver returned.

**The row lock ships here, not with its callers.** Chosen: `lock_user_for_update` in PR 1. Why:
both callers are in PR 2, and a primitive shared by two callers belongs to the pull request before
them. It closes a race neither B-11 nor B-13 names, which the pre-Gate-1 review found: a login can
read a user, verify the old password, and be descheduled; a password change can then commit its
new hash and revoke every other session; the login then inserts a live session built on the
credentials that change just revoked. A transaction around each flow separately does not close it.

**The expiry is judged after the row is fetched, not in the WHERE clause.** Chosen: select the
session by token hash, then compare `expires_at`. Alternative: filter on the expiry in SQL, which
is one statement instead of a statement and a comparison. Why: filtering makes an expired session
and a token that never existed both return nothing, and they are different answers. A client that
can tell them apart can prompt for a fresh sign-in rather than reporting a generic failure.

**`last_seen_at` is a conditional UPDATE.** Chosen: the five-minute condition inside the
statement. Alternative: read the row, decide, write. Why: the alternative is a write per
authenticated request for a column nothing reads at that resolution, and two requests arriving
together would both read the same stale value and both write. Postgres evaluates the condition
against the row it has locked, so the second request updates nothing.

## Testing

Twenty-six tests, authored by Codex through `codex exec` (R-907) and proved red under
`enforce/tdd.sh red` before any implementation existed. 220 passing in total, green on the first
run. `ruff`, `black` and `mypy --strict` clean.

Three are worth naming because they rule out implementations that look right:

- The **AST test** on `verify_password`, which asserts one return, one await, no conditional, and
  that the awaited comparison receives what the resolver returned. No value assertion reaches that.
- The **row-lock test**, which reads `pg_blocking_pids` to see Postgres actually report the second
  transaction waiting on the first, rather than inferring blocking from elapsed time.
- The **`last_seen_at` concurrency test**, which compares `xmin` and `ctid` as well as the
  timestamp, so a redundant write cannot hide behind two writes landing in the same instant.

## Reflection

What is clearer now: a property about _how_ something is computed cannot be tested by looking at
what it returns, and the honest options are to make the computation structural or to leave the
property untested and say so. This is the fourth time in two slices that the same shape of defect
has come up, after the security-headers test that wrapped a bare `Response`, the rate limiter's
atomicity, and the first draft of the dummy-hash test here. Extracting the decision into a pure
function is the move that works, and the AST test is the belt to that braces.

What I got wrong first, twice, both caught by me rather than review: the email lookup used `ILIKE`,
which reads the underscore in an address as a wildcard and would not use the functional unique
index the slice 02 migration created for exactly this comparison. And the dependency returned the
joined session row straight through as `user`, so `user.id` was the session's id rather than the
user's. Both were the kind of mistake that passes a casual read and fails a test.

## Codex review

Reviewed by Codex through `codex exec` against the plan's PR 1 block and this document (R-517).
Two findings, both real, both fixed. The tests for them came from the `test-author` fallback,
because Codex reached its usage limit immediately afterwards (R-907).

1. **P1. The session resolvers could not be used as FastAPI dependencies.** Both declared
   `connection: AsyncConnection` with no `Depends` marker, so FastAPI would read the parameter as
   request data and refuse to register any route using `Depends(get_current_user)` with
   `Invalid args for response field`. The integration tests called the resolvers directly, which
   concealed it completely: a pull request whose stated purpose is to deliver a dependency shipped
   one that could not be depended on. Fixed with a module-level
   `RequestConnection = Annotated[AsyncConnection, Depends(get_connection, scope="function")]`.
2. **P2. The structural test was still defeatable.** The AST assertions accepted a verifier that
   wrapped bcrypt in a lambda carrying the condition:
   `await asyncio.to_thread(lambda h: stored_hash is not None and bcrypt.checkpw(...), comparison_hash)`
   satisfies one return, one await, no conditional, and an argument mentioning the resolved hash,
   while skipping bcrypt entirely for an unknown user. That is the timing property B-11 exists to
   require, so the test asserted the shape and missed the substance. Tightened to require that the
   awaited call is `asyncio.to_thread`, that the callable handed to it is `bcrypt.checkpw` itself
   as an attribute rather than a wrapper, and that the candidate and the resolved hash are its
   direct arguments.

Both were demonstrated rather than asserted. The P1 mutation was applied through a scratch pytest
plugin that swaps the module in `sys.modules`, because the protected-path guard correctly refused
to let the test author edit production under R-411: the mutant fails all nine new tests at route
registration, the real implementation passes them, and the pre-existing integration tests pass
under the mutant, which is the control proving they concealed the defect. The P2 mutation fails
only the new test and passes every other test in the file, including the original structural test.

The author also checked whether `hash_password` has the same hole and found it does not, for a
reason worth recording: a wrapper around `hashpw` still has to produce a real salted cost-12 hash
that verifies, so declining to do the work cannot produce a passing value. `verify_password` is
different only because a correct-looking answer, `False`, is available without doing any work at
all. That is the general shape of the problem: structural pinning is needed exactly where the
right answer is cheap to fake.

Copilot review was not requested (R-514), and its ruleset is disabled.
