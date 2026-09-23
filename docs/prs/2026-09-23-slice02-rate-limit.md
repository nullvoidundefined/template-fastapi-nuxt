# Slice 02, PR 5: rate limiting and the Redis settings guard

**Ticket:** IAN-171
**Branch:** `feat/slice02-rate-limit`
**Plan:** `docs/slices/slice-02-data-and-errors.md`, the PR 5 block
**Story:** US-INFRA-008

## Summary

This is the last pull request in slice 02 and the one with a real attacker in its threat model.
A limiter keyed on something the client controls is not a limiter, so the substance here is the
key derivation rather than the counting: the middleware reads the address uvicorn resolved and
never looks at `X-Forwarded-For` itself, and compose is changed so that uvicorn has exactly one
address to trust rather than a private range.

Two buckets, 100 requests per 15 minutes globally and 10 on the four auth paths, counted in Redis
so every replica shares one budget. Without Redis outside production the limiter counts in process
and says so once. Production never counts in process: when Redis is gone the four auth paths fail
closed with 503 and everything else is served.

## What changed

- **`app/middleware/rate_limit.py`.** The limiter, its Lua counter, and the in-process fallback.
- **`app/constants/rate_limits.py`.** Both limits, the window, and the four auth paths as full
  mounted paths including the `/v1` prefix.
- **`app/constants/exempt_paths.py`.** `RATE_LIMIT_EXEMPT_PATHS` beside the CSRF set.
- **`app/errors.py`.** `send_error_envelope` gains an optional `headers` argument, which
  `Retry-After` needs and which the function did not have.
- **`app/main.py`.** The limiter fills the slot reserved for it at position 4.
- **`docker-compose.yml`.** A fixed subnet on the project network, a static address for `web`, and
  `FORWARDED_ALLOW_IPS` narrowed from `172.16.0.0/12` to that one address.
- **`README.md`.** `REDIS_URL` is now read by the API as well as the worker, `FORWARDED_ALLOW_IPS`
  has a local value where it had none, and a paragraph explains what that list is for.

## Architectural decisions

**One Lua script rather than `INCR` plus `EXPIRE`.** Chosen: a script that increments and arms the
expiry in one server-side operation, setting the expiry only when the counter is new. Alternative:
`INCR` followed by `EXPIRE`, or read-decide-write. Why: the plan said the counts are "counted in
Redis so that every replica shares them", which describes where the count lives and not that
checking it is one operation. Two round trips admit more than the limit when requests race, and a
process that dies between them leaves a key with no expiry that never resets, locking that client
out permanently. Setting the expiry only on the new key also keeps the window fixed; re-arming it
on every request would mean a steady client never escapes its window at all.

This is the correction IAN-171 carried in, and it is invisible to every sequential test. "The
eleventh request answers 429" passes against a read-then-write counter, because nothing interleaves.
The concurrency test is what fails, and it was verified by mutation: replacing the script with a
read-then-write counter makes both it and the window test fail, and restoring it makes them pass.

**Never parsing `X-Forwarded-For`.** Chosen: read `scope["client"]`, which uvicorn has already
resolved under `--proxy-headers`. Why: every entry in that header except the last is supplied by
the client. A limiter that read it would let anyone rotate buckets by prepending an address, which
is the whole attack. Trusting uvicorn means the trust decision is configuration, in
`FORWARDED_ALLOW_IPS`, rather than code that could be subtly wrong.

**A fixed compose address instead of the private range.** Chosen: a user-defined subnet and a
static IPv4 for `web`. Alternative: keep `172.16.0.0/12`. Why: uvicorn's allowlist takes addresses
and CIDRs, never a service name, and compose allocates addresses dynamically, so the choice was
between trusting every container in the range and naming an address that changes. Trusting the
range means any container on it can forge a client address, which makes the limiter's key only as
good as the weakest container. The static assignment removes the choice.

**Failing the auth paths closed, and only them.** Chosen: in production, a Redis failure answers
503 on the four auth paths and serves every other route. Alternative: fall back to counting in
process. Why: a per-replica count multiplies the effective limit by the replica count, and a
client resets it by reconnecting, so the fallback is not a weaker limit but very nearly none. The
trade is that a Redis outage costs four endpoints rather than the API.

## Testing

Twenty tests. Codex was at its usage limit when this PR started, so they came from the recorded
`test-author` fallback (R-907), which is noted here and on the ticket.

- **Against the real Redis:** the eleventh request on each of the four auth paths, the hundred and
  first of any kind, `/v1/auth/me` inside the global bucket and outside the auth one, the health
  routes and the webhook served after the global bucket is spent, the parallel atomicity case, and
  a TTL test that reads the key's expiry twice to prove the window does not slide.
- **Through uvicorn's `ProxyHeadersMiddleware`:** two proxied addresses counted separately, a
  forged `X-Forwarded-For` counted in the client's own bucket, and a direct request keyed on its
  peer. These are wrapped deliberately: driven through the suite's bare `ASGITransport` the forged
  header case would pass whether or not the limiter parsed the header, which is the failure it
  exists to rule out.
- **The production outage in both forms, separately:** a connection cut mid-run by a TCP relay in
  front of the real Redis, and a first connection to a closed port. Each asserts the 503 envelope
  on all four auth paths, a normal route served, `rate_limiter_unavailable` logged, and more than
  the global limit of requests still served afterwards, which is how "no in-memory fallback in
  production" is asserted rather than inspected.
- **Without Redis:** one in-memory bucket shared across requests, the warning logged exactly once,
  and a fresh application starting with an empty count.

Full server suite: 188 passed. `ruff`, `black` and `mypy --strict` clean. The whole stack was
brought up on the new network and came back healthy, with `web` holding `172.28.0.10`, the address
`FORWARDED_ALLOW_IPS` names.

## Reflection

What is clearer now: the reason this ticket carried an explicit correction is that the plan's own
wording hid the defect. "Counted in Redis so that every replica shares them" reads like a complete
specification and is not one, because it fixes where the state lives and says nothing about whether
reading and writing it is one operation. Every test the plan listed would have passed against an
implementation that loses counts under load. The concurrency test had to be asked for by name.

What I got wrong first: when I checked the atomicity test by mutation, my mutation script matched
a string that `black` had already reformatted, so the edit silently did nothing and the suite
passed. I read that as the test failing to discriminate and said so. Adding an assertion that the
replacement actually matched showed the opposite: the test fails under a read-then-write counter,
and under a re-armed expiry as well. A mutation check that cannot fail is worth less than no
mutation check, because it produces a confident wrong answer.

## Pre-merge review

Codex was at its usage limit, so the review came from a fresh Claude agent on an equal model, the
recorded R-517 fallback. Seven findings. The reviewer ran the code rather than reading it, which is
how the first one was established.

1. **P0, blocking. A Redis that stops answering hung every route.** The client carried no
   timeouts, and this middleware is registered outside `RequestTimeoutMiddleware`, so the 30 second
   deadline had not been entered when the Redis call was awaited. Both outage tests reproduced
   failures that raise promptly, a closed port and a cut connection; the common production failure,
   a Redis that holds the socket open and stops replying during a failover or partition, was
   untested and blocked indefinitely. The reviewer demonstrated it against a socket that accepts
   and never answers: no response after 45 seconds. That inverts the failure-mode contract this PR
   is built on, where a Redis outage costs four endpoints rather than the API. Fixed with both
   socket timeouts at 2 seconds, well inside the request timeout; redis-py's `TimeoutError`
   subclasses `RedisError`, so it lands in the handler that was already there.
2. **P1. Staging took the in-memory fallback.** The check was against production alone, so a
   deployed multi-replica environment got per-replica counting, which the spec itself calls very
   nearly no limit. Settings require `REDIS_URL` in production but not in staging, so staging could
   also run with none at all. Fixed with a `DEPLOYED_ENVIRONMENTS` set covering both, mirroring
   `app/db/engine.py`, and a deployed environment with no `REDIS_URL` now takes the outage path.
3. **P2. The script armed the expiry only on a new key.** Any key that ever reached Redis without
   a TTL was incremented forever, locking that client out permanently, while `normalize_retry_after`
   hid the symptom. Fixed by arming whenever the TTL is negative, which keeps the window fixed.
4. **P2. The discarded client leaked its pool**, once per failed request outside production. The
   reset bought nothing, since redis-py reconnects on the next command. Removed.
5. **P2. The in-memory window map was never evicted**, growing with every distinct source address.
   Closed windows are now swept on write.
6. **The fixture fix covered half the suite.** Pointing `build_server_app` at a closed port left
   the `server_app` fixture, which backs about eleven modules, inheriting whatever `REDIS_URL` the
   shell exports. The reviewer showed the accumulation is real by setting the ambient counter to 95
   and rerunning: nine failures across three modules that have nothing to do with rate limiting.
   Fixed the same way, and the docstring's claim is now true.
7. **P3. `Retry-After` was not exposed to cross-origin callers.** Sent on the wire but unreadable
   by `fetch`, which makes the limit unactionable for exactly the clients `CORS_ORIGIN` exists for.
   Added, along with the request ID.

Each fix was verified by reverting it and confirming the matching test fails. Finding 7 is the one
change in this PR with no test: nothing asserts `Access-Control-Expose-Headers`, and it is recorded
here rather than left implicit.

The reviewer also noted that `e2e/global-setup.ts` losing its `--no-deps` flag belongs to a
different scope than rate limiting. It is here because the pre-push hook runs the end-to-end suite
and the flag made it depend on a stack that was already running.
