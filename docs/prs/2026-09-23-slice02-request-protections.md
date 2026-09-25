# Slice 02, PR 4: security headers, CORS, the CSRF guard, and the request timeout

**Ticket:** IAN-170
**Branch:** `feat/slice02-request-protections`
**Plan:** `docs/slices/slice-02-data-and-errors.md`, the PR 4 block
**Story:** US-INFRA-007

## Summary

Slice 03 opens a public login route. These are the protections that have to be in place before it
does, rather than retrofitted onto it afterwards, which is why they ship as one pull request: they
are a single concern, the ordered ASGI chain, and the order in which they wrap each other is the
part worth reviewing once instead of three times.

Four things land. Security headers decorate every response. CORS is restricted to one configured
origin with credentials allowed. A CSRF guard rejects a state-changing request that does not carry
`X-Requested-With`. And a timeout cancels a handler that runs past 30 seconds. Settings gain the
two fields the first two need, and production now refuses to start without the three values whose
absence would quietly weaken a protection rather than fail loudly.

## What changed

- **`app/middleware/security_headers.py`.** `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: strict-origin-when-cross-origin` on every response, with
  `Strict-Transport-Security` added only under production.
- **`app/middleware/csrf_guard.py`.** 403 `CSRF_HEADER_MISSING` for an unsafe method without the
  header. Safe methods are never checked. It logs `csrf_header_missing` when it rejects.
- **`app/middleware/request_timeout.py`.** `asyncio.timeout` around the downstream app, answering
  408 `SERVER_REQUEST_TIMEOUT`.
- **`app/constants/exempt_paths.py`.** The two health routes and `/v1/billing/webhook`, as a
  frozenset compared by equality.
- **`app/core/settings.py`.** `cors_origin` and `forwarded_allow_ips`, plus the
  `require_production_values` validator.
- **`app/errors.py`.** `send_error_envelope`, the raw-ASGI envelope writer both new guards use.
- **`app/main.py`.** The ordered `register_middleware`, now taking `Settings`, and CORS configured
  from `cors_origin`.
- **`README.md`.** The `CORS_ORIGIN` row and a paragraph naming the three values production
  requires, with the reason each one matters.

## Architectural decisions

**Writing the rejection as raw ASGI messages rather than raising.** Chosen: both guards call
`send_error_envelope`, which sends `http.response.start` and `http.response.body` directly.
Alternative: raise an `AppError` and let `register_exception_handlers` answer it, as a route does.
Why: these are pure ASGI classes registered with `add_middleware`, which places them outside
Starlette's `ExceptionMiddleware`. An `AppError` raised there never reaches the handlers and the
client gets a bare 500 with no code at all, which is exactly the failure the error envelope exists
to prevent. `app/middleware/request_context.py` already faced this for its 413 and solved it the
same way; this pull request extracts that into one function all three now share, which is why
`request_context.py` appears in the diff without its behavior changing.

**Exemptions compared by equality, not prefix.** Chosen: a frozenset and an `in` test. Why: a
prefix match exempts more than it names. `/health/ready-not-really` and
`/v1/billing/webhook-spoof` both begin with an exempt path, so under prefix matching anyone who
can get a handler mounted below an exempt path gets a CSRF-free route. There is a test for exactly
that pair, and it is the one that fails if the implementation is ever loosened.

**The ordering test asserts a log line, not only headers.** Chosen: the CSRF guard emits its own
`csrf_header_missing` event, and the test asserts that event carries the inbound request ID. Why:
the header assertions alone pass under either order, because the correlation middleware sets the
response header from a context variable that survives regardless of where the request context sits.
Only a log line emitted during the rejection proves that `RequestContextMiddleware` was still
outside the guard when the guard ran. The first draft of this test reached that assertion by
monkeypatching `CsrfGuardMiddleware.__call__` to emit a line of its own; that was replaced, because
it tested the patch rather than the application. Making the guard log its own rejection is better
anyway: the client is told nothing beyond the code, so that line is the operator's only record.

**Cancelling the handler, not just answering 408.** Chosen: `asyncio.timeout`, which cancels the
task. Alternative: race the handler against a sleep and answer whichever finishes first. Why: the
point is to release the worker, the connection, and the upstream request. A timeout that answers
while the handler runs on unobserved leaks exactly the resources the limit exists to protect. The
test asserts the handler observed its own cancellation, so the weaker implementation fails.

## Testing

Thirty-four new tests, authored by Codex through `codex exec` (R-907), red before the
implementation existed and green after.

- **Security headers:** 16 cases across four environments and four status codes, including 403 and
  500, so the headers are proven on rejections and not only on successes. Plus a CORS preflight
  test with both an allowed and a denied origin, the allowed case being the control that would fail
  if the CORS middleware were simply absent.
- **CSRF:** the envelope body asserted exactly rather than only the status, across all four unsafe
  methods; the header case; the safe-method case; the three exemptions; and the two prefix-spoofing
  paths.
- **Timeout:** the exact 408 envelope with an injected 5 millisecond deadline, plus an assertion
  that the handler observed cancellation.
- **Ordering:** one test covering the request-ID header, the security headers, and the bound log
  context on a single rejection.
- **Settings:** one case per missing production value, and one that all three are retained.

Nineteen previously passing tests failed once the guards landed, all for the right reason: they
made state-changing requests without the header, or built a production application without the new
values. Codex updated them to send the header and to supply the configuration, changing no
assertion's intent. Sending the header is what a real client does, since the frontend sets it as a
base header on every request, so those tests were unrepresentative before rather than after.

Full server suite: 168 passed. `ruff`, `black`, and `mypy --strict` clean.

## Reflection

What is clearer now: the middleware order is not a style question, and the thing that makes it
enforceable is choosing an assertion the wrong order actually breaks. Headers were the obvious
thing to assert and they would have passed under an order that loses the request ID from every
log line a guard emits. The test only became worth having once it asserted something that lives
inside the chain rather than something observable from outside it.

What was wrong first: the first version of that test reached the right assertion by patching the
class under test. It would have passed, and it would have kept passing if the guard stopped
logging entirely, because the line it observed was the test's own. Replacing it meant deciding
that the guard should log its own rejection, which turned a test-only construct into real
behavior an operator benefits from.

## Codex review

Reviewed by Codex through `codex exec` against the plan's PR 4 block and this document (R-517).
Four findings, all real, all fixed in `97998aa`, with 14 regression tests added.

1. **Security headers were missing from the two responses that leave outside the chain.** The
   body limit in `RequestContextMiddleware` answers its own 413 without calling anything below it,
   and Starlette's `ServerErrorMiddleware` writes the unhandled 500 outside every user layer. The
   original test passed because it wrapped the middleware around a bare `Response`, never around
   the real application. Fixed by registering the headers outermost, and by having the 500 handler
   set them itself for the same reason it already set the request ID by hand.
2. **A blank string satisfied the production validator.** It tested only for `None`, so
   `CORS_ORIGIN=` in an env file started production with an empty allowed-origin list. Fixed with
   an `is_blank` check that unwraps `SecretStr`.
3. **Managed headers were appended rather than replaced.** A route setting its own
   `X-Content-Type-Options` produced two conflicting values. Codex found a second-order bug in the
   first fix: the managed set was derived from the headers being sent, so outside production
   `Strict-Transport-Security` was not in it and a downstream copy survived in exactly the
   environments that must never send it. The managed set is now fixed rather than derived.
4. **A handler's own `TimeoutError` was relabelled 408.** The `except` caught every `TimeoutError`
   raised inside the block, so an upstream call timing out became a request timeout and never
   reached the 500 handler. Fixed by checking the `asyncio.timeout` context's `expired()` state
   and re-raising otherwise.

Each fix was verified by reverting it and confirming its tests fail. A second review pass over the
fix range found no defects and no regressions introduced by the fixes themselves.

Copilot review was not requested (R-514).
