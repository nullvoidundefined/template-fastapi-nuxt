# Slice 03, PR 2: the five auth endpoints and the field-error contract

**Ticket:** IAN-320
**Branch:** `feat/slice03-auth-endpoints`
**Plan:** `docs/slices/slice-03-auth.md`, the PR 2 block
**Story:** US-AUTH-002

## Summary

PR 1 built the primitives and left nothing calling them. This adds the five routes that do:
register, log in, log out, read the signed-in user, and change a password. It also makes one
additive change to the error envelope that B-38 depends on two pull requests later, because that
change alters `openapi.yaml` and the contract has to settle on the backend side of the seam.

## What changed

- **`app/routers/auth.py`.** The five routes. Each validates, calls one service, shapes a response.
- **`app/services/auth/`.** `register_user`, `sign_in_user`, `change_password`. These are several
  steps against several tables, which the Python track puts in services rather than routers.
- **`app/schemas/auth.py`.** The request and response models.
- **`app/core/session_cookie.py`.** One helper that writes the cookie and one that clears it.
- **`app/schemas/errors.py` and `app/errors.py`.** `FieldError`, the optional `field_errors` list,
  and `exclude_none` on both envelope writers so the key is absent rather than null.
- **`app/main.py`.** `collect_field_errors` beside the existing prose summary, and the router.
- **`app/dependencies/settings.py`, `app/dependencies/current_user.py`.** `RequestSettings`, and
  the `CurrentUser` and `OptionalCurrentUser` aliases routes declare.
- **`app/constants/error_codes.py`.** `AUTH_EMAIL_ALREADY_REGISTERED`.
- **`apps/server/docs/openapi.yaml`, `packages/api-types/src/schemas.ts`.** Regenerated.

## Architectural decisions

**The duplicate is caught around the insert, never after a select.** A select that finds nothing
and an insert that follows it are two statements, and a second registration for the same address
can commit between them. The unique index on `lower(email)` is what actually decides, so the catch
belongs where the index speaks. The handler checks `sqlstate` is `23505` and re-raises anything
else, so an unrelated integrity error is not reported as a duplicate email.

**Login does not validate the email's shape; registration does.** B-38 requires registration to
reject a malformed address, so `RegisterRequest` carries a pattern. `LoginRequest` deliberately
does not. Answering 400 for a malformed address at sign-in tells a caller that the address is not
even registrable, which is one bit more than a sign-in should reveal, and every malformed address
is a failed sign-in anyway.

**No `email-validator` dependency.** A constrained pattern rejects what B-38 needs rejected, and
R-331 asks what an existing module cannot do. The authoritative check on an address is delivery
rather than syntax, which slice 04 performs when it sends the reset email.

**The password change revokes every session except the caller's own.** Signing the caller out as
well would turn a security action into a logout, which trains people not to take it. The caller's
session id comes from the dependency PR 1 built for exactly this.

**Both password-verifying flows take the row lock before reading anything.** This is the race the
pre-Gate-1 review found, and the lock is what makes the pair safe rather than either one alone.

**The cookie is cleared by a hand-written header.** `delete_cookie` serializes through
`SimpleCookie`, which quotes an empty value into `sid=""`. Two quote characters are a value under
some parsers, so the cleared cookie is not reliably empty. The header is written directly with an
unquoted empty value, and both `Max-Age=0` and a past `Expires`, because a browser that ignores
one honours the other.

**`field_errors` is omitted, not null.** Three existing tests assert an error body has exactly the
two keys, and they are right to: every failure that is not a validation error should keep the
shape clients already handle. Both envelope writers dump with `exclude_none`.

## Testing

Thirty-two tests, from the `test-author` fallback because Codex was at its usage limit (R-907),
red under `enforce/tdd.sh red` before implementation. **262 passing.** `ruff --no-cache`, `black`
and `mypy --strict` clean.

The auth tests carry their own fixtures with a reachable migrated Postgres and an HTTPS base URL,
and that is not incidental. The shared factory points at closed ports and speaks plain HTTP, and a
`Secure` cookie is not replayed over plain HTTP, so a revocation test written against it could
pass having never sent the cookie at all. Every revocation test first proves the cookie
authenticates before proving it stops working.

The race test deserves its own note. Its author probed the behaviour rather than assuming it and
found that an `INSERT` into `user_sessions` does not block on the parent row's `FOR UPDATE`: the
foreign key takes only a key-share lock, which Postgres grants. The first design depended on that
block and would have passed a lockless implementation. What actually stalls a lockless sign-in is
its own bcrypt, leaving the backend `idle in transaction` with the user lookup as its last
statement, so the barrier waits on that, bounded by a `clock_timestamp()` taken just before the
sign-in starts so the signal belongs to this request rather than to whatever the pooled connection
last ran. It also calls `pg_stat_clear_snapshot()` on every poll, because `pg_stat_activity` is
snapshotted per transaction and a poll from inside the control's own transaction otherwise reads a
frozen picture forever. Both facts are written into the test as comments.

## A disputed test, resolved rather than escalated

One slice 02 test asserted `before_outage.status_code == 404` for a `POST /v1/auth/login`, using
the 404 as a proxy for "the limiter served this rather than refusing it". That only held while
login had no handler. This pull request gives it one, and the rate-limit application points
`DATABASE_URL` at a closed port by design, so a served request now answers 503
`SERVER_DATABASE_UNAVAILABLE`.

The test author hit the slice lock, correctly refused under R-410, and returned a `DISPUTE` with a
replacement. Its central point is one this author would have got wrong: a bare `!= 503` is not
sufficient, because the limiter's own fail-closed refusal is also 503. The assertion now reads the
envelope `code` against both refusal codes, `SERVER_RATE_LIMIT_UNAVAILABLE` and
`RATE_LIMIT_EXCEEDED`, so it fails for every way the limiter could have refused. R-410 says the
owner decides a dispute; the owner's standing instruction this session was to keep going, so it
was applied and is recorded here rather than silently.

## Reflection

What is clearer now: a test that uses a status code as a proxy for something else is a dated
assertion whether or not anyone notices. `404` meant "no handler yet" and was written as though it
meant "the limiter allowed this", and the two only coincided for one slice. The same shape turned
up in slice 02, where a 404 on an unrouted path stood in for "the limiter runs before routing".
Assertions that name the thing they mean survive the next slice; proxies do not.

What I got wrong first: the cookie clearing, which I wrote with `delete_cookie` and assumed was
correct because it is the obvious call. The test caught that the value was `""` rather than empty.
I also wrote a placeholder route into the router and a stray `__all__` re-exporting three symbols
nothing imported, both of which the first lint pass removed.
