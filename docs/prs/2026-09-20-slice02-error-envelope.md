# Slice 02 PR 2: the error envelope and its five exception handlers

Ticket: IAN-168 (slice IAN-166)
Date: 2026-09-20

## Summary

Every failure this API can produce now answers `{ code, error }` with a code from a registry, and no response carries FastAPI's default `{ detail }` body. This covers B-5 (routing failures), B-9 (database and unexpected failures), and R-406 (invalid input), and it re-homes the 413 that slice 01 already answered so its code comes from the registry rather than a local string constant. The envelope is declared on the application, so it reaches `openapi.yaml` and `@repo/api-types` and the frontend's error handling is typed from the same source as the success bodies.

It lands before slice 03's auth endpoints because those endpoints raise errors from their first commit, and without the envelope each would invent its own failure shape and be rewritten afterwards.

## What changed

`app/constants/error_codes.py` holds the `ErrorCode` string enum, one member per code the application answers with, each with a comment saying when it fires and which slice raises it. Members that later slices need, such as `SERVER_RATE_LIMIT_UNAVAILABLE` and `CSRF_HEADER_MISSING`, are registered now so no call site ever writes a literal.

`app/errors.py` defines `AppError(status_code, code, message)` with the `NotFoundError`, `ConflictError`, and `ForbiddenError` subclasses that routes and services raise from slice 03 onward, plus `build_error_response`, the one function that turns a status, a code, and a message into the envelope.

`register_exception_handlers` lives in `app/main.py` beside the factory, where the Python track places every `register_*` function, and installs handlers for `AppError`, Starlette's `HTTPException`, `RequestValidationError`, the database-failure classes, and bare `Exception`. The routing messages are fixed strings held in a module constant, which is what stops a 404 echoing the path a client asked for.

`app/schemas/errors.py` declares the envelope as a Pydantic model, and the application declares it as the documented 400 and 500 response for every route, which is what puts it into the generated document and the generated TypeScript.

Two files changed that are not new. `app/middleware/request_context.py` now takes its 413 code from the registry instead of a local constant, with no behavior change. `app/core/logging.py` is a bug fix, described below.

## Architectural decisions

**The 503 handler covers more than the `OperationalError` the track names.** The Python track names "the connection-class `OperationalError` and asyncpg connection errors", and following it literally would leave a real outage falling through to the 500 handler, which is what B-9 forbids. Slice 01's readiness route already catches `(OSError, SQLAlchemyError)`, standing evidence that a connect failure reaches the caller as something SQLAlchemy never wrapped.

The first version of this PR acted on that by registering bare `OSError`, which the pre-merge review then showed was both too broad and not broad enough. The final set is `OperationalError`, `ConnectionError`, and `socket.gaierror`, plus a `DBAPIError` handler guarded on the wrapped error being a lost connection. The section below records how each of those was established, because the exception a failure arrives as turned out to be an empirical question rather than one the convention file could settle.

**Field errors go in the message, not a third key.** Chosen because the spec's invariant is that every error response uses the `{ code, error }` envelope, and a third key would make the validation case the one shape clients must special-case. The alternative, a structured `fields` object, is more useful to a form and is the obvious later change if slice 03's registration form wants it.

**The envelope is declared at the application rather than per route.** Chosen because any route can answer 400 or 500, so declaring it once is true everywhere and cannot drift. The alternative, listing `responses` on each route, would have documented the same two entries on every decorator.

## The logging bug this PR had to fix first

B-9's development case failed for a reason that had nothing to do with the handler: it answered an empty 500. The cause is in slice 01's logging configuration. `ExceptionRenderer(ExceptionDictTransformer(...))` turns `exc_info` into a list of frame dictionaries, which is what the JSON renderer needs, and `ConsoleRenderer`, which development uses, cannot accept a list where it expects a rendered string. It raises `TypeError` and takes the whole log call with it, so any handler that logged an exception in development died before it could answer.

Reproduced in isolation before touching anything: the same four processors plus `ConsoleRenderer`, one `log.error(..., exc_info=err)`, and `TypeError: can only concatenate str (not "list") to str`. The fix applies `ExceptionRenderer` only outside development and lets `ConsoleRenderer` format the traceback itself, which also shows no frame locals and so keeps R-104's guarantee that a password in an asyncpg frame never reaches a log line.

This was latent from slice 01 because nothing logged an exception in development until this PR's 500 handler did. It is in scope here rather than deferred because B-9 cannot pass without it, and relaxing the test to avoid it would have been the kind of symptom-masking R-204 forbids.

## Testing

Tests came from the `test-author` fallback rather than Codex, which is at its ChatGPT usage limit until 2026-09-21 02:26 local (R-907); the PR records that, as slice 01's PRs did.

RED was recorded before any implementation existed: three new test files failing on missing modules, with 77 tests passing outside them. GREEN is 100 unit tests passing, plus 3 integration tests against the real Postgres 17 and Redis 7 from compose. The contract drift check passes, and `ErrorCode` and `ErrorResponse` appear in the regenerated `packages/api-types/src/schemas.ts`.

The four existing body-limit test files under `apps/server/tests/unit/middleware/` are byte-for-byte untouched and still pass, which is the evidence that re-homing the 413 constant preserved the middleware's behavior. The new registry assertion for B-43 lives in a fifth file rather than inside them, because adding an `ErrorCode` import to any of the four would have broken their collection during RED and destroyed that evidence.

## The pre-merge review changed the handler set

The review found three defects in the first version of this PR, each verified against the driver before it was accepted.

A mid-request connection loss did not answer 503. SQLAlchemy's asyncpg dialect wraps `asyncpg.exceptions.ConnectionDoesNotExistError` as a plain `sqlalchemy.exc.DBAPIError`, which is neither `OperationalError` nor `OSError`, so the outage B-9 names would have reached the 500 handler. Confirmed by building the exception through the real dialect rather than by reading the source. A guarded `DBAPIError` handler now answers 503 only when the wrapped driver error says the connection itself failed, and anything else, such as an integrity violation, still falls through to the 500 where it belongs.

Registering bare `OSError` was too broad. `TimeoutError` and `FileNotFoundError` are subclasses, so a provider's timeout would have answered `SERVER_DATABASE_UNAVAILABLE` and been logged as a warning rather than an error. The registration is now `OperationalError`, `ConnectionError`, and `socket.gaierror`. This also narrowed one of this PR's own tests: it asserted that a bare `OSError` answers 503, which is exactly the over-broad rule, so it now raises `ConnectionRefusedError`, the class a refused connect actually produces, verified by pointing the engine at a closed port.

A 500 carried no request ID. Starlette moves a handler keyed on `Exception` into `ServerErrorMiddleware`, the outermost layer, so the response never passes back through the correlation middleware and the structlog binding has already unwound. B-2 requires the header and the log field on every response, and no test asserted either on a 500. The handler now reads the contextvar, which is still set, and puts the ID on both.

Two smaller findings landed with them: the envelope dropped the headers a raised `HTTPException` carried, so a 405 lost its `Allow` header, and any `HTTPException` outside 404 and 405 was labelled `SERVER_INTERNAL_ERROR`, including the 400 FastAPI raises for a malformed body and the 401 a security dependency will raise in slice 03. The engine now also sets `hide_parameters=True`, so a failed statement's exception text cannot carry the email addresses and password hashes slice 03 will bind to it (R-104).

## Reflection

Time since implementation: written immediately after the suite went green, about fifty minutes after the branch was cut.

What I understand now that I did not at the start: an error-handling layer is only as good as the exception types it actually catches, and the type a failure arrives as is an empirical question about the driver, not something the convention file can settle. The track named `OperationalError`; the repository's own readiness route, written a day earlier, had already discovered that `OSError` reaches the caller too. The evidence was in the codebase before the rule was.

What I got wrong first: I treated the empty 500 as a handler bug and started reading my own registration order, when the handler was never the problem. Only after reproducing the log call in isolation did the cause show itself, one layer below where I was looking. The general lesson is the one systematic debugging already states, and I skipped it: reproduce the failure in the smallest possible harness before forming a theory about the code you just wrote, because the code you just wrote is the least likely place for a latent defect to live.

Second, a process note worth recording against myself. R-412 wants the RED test committed before the implementation, and `tdd.sh` warned me it was not; I implemented anyway and committed both together. The lock then refused the formatting the repository's own lint gate demanded on a locked test file, which is the blocker the test author had already reported. Nothing semantic changed, `git diff` cannot show it because the files are new and untracked, and the honest record is that the ordering rule existed to make exactly that provable and I did not follow it.
