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

## The pre-merge review, and what it changed

Codex was at its usage limit, so R-517's stated fallback ran: a separate Claude agent on an equal
model, given the diff, the plan, the Python track and what PR 1 had landed. It returned two P1
findings and seven P2. Both of the plan's named review foci came back clean, with the evidence
quoted rather than asserted: the duplicate `try` wraps only the insert, so a unique violation on
`user_sessions.token_hash` cannot be reported as a duplicate address, and the password change
deletes `user_id = ... AND id != session_id` with a test asserting both directions.

**The first P1 was a real defect this author had reasoned about and got backwards.** The password
ceiling was `Field(max_length=72)`, which Pydantic counts in characters, while the pinned bcrypt
refuses anything past 72 **bytes** and raises rather than truncating. A password of thirty-seven
accented characters therefore passed validation, reached `hashpw`, and answered 500 on register,
login and the password change alike. The comment beside the constant asserted the opposite, that
bcrypt "silently truncates", which was true of older bcrypt and is the reason the wrong unit
looked right. Every password field now carries a validator on the encoded length, so the refusal
is a 400 naming its own field, and the boundary is tested from both sides: seventy-two bytes of
multi-byte text still registers, so the fix cannot degenerate into rejecting non-ASCII.

**The second P1 was procedural.** The `Access-Control-Expose-Headers` test the plan's Contents
block requires had been written but never committed, so CI never ran it and the constant it exists
to observe stayed unobserved. It is committed.

Four findings were fixed with their tests. The password change is now keyed on the id the session
resolved to rather than the address it carries, because an address is a value users are expected
to change and an authorization subject re-derived from one is only accidentally correct.
`PATCH /v1/auth/me` joins the auth rate-limit bucket: the bucket matched on path alone, and the
path had to stay out of it for the `GET` a signed-in page makes on every navigation, so a
password-verifying route sat on the global limit of one hundred. The limiter now matches the
method as well, with the `GET` asserted to stay out, since that is the direction a naive fix
breaks. And the password comparison in both services is bound to a name on its own line rather
than written into the guard: `if not await verify_password(...) or user is None` is correct only
because Python evaluates the left operand first, the reordering a reviewer would naturally reach
for restores exactly the enumeration oracle B-11 forbids, and every test in the suite stayed green
through that edit. An AST test now pins the shape in both callers, which is the same lesson this
slice has now learned five times: pin the structure wherever a correct-looking answer is cheap.

Two findings were answered rather than changed. The race test counted every backend in the
database, so a sharded run would have seen another worker's blocked transaction; it now counts
only its own, through a per-run `application_name`, with the barrier and the `clock_timestamp()`
bound untouched because the review confirmed both correct. And the cost of the row lock is now
recorded rather than implied: bcrypt runs inside the request transaction, and in login and the
password change inside the row lock, so about 250 ms of a pooled connection is held per auth
request and sign-ins for one account serialize. That is the consequence of the lock Gate 1 chose,
bounded by the auth bucket, and measuring it before changing it is IAN-330.

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
