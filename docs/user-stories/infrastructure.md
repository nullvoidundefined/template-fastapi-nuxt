# Infrastructure User Stories

## US-INFRA-001: Liveness and readiness endpoints

**As** an operator running the API on Railway
**I want to** probe whether the process is alive and whether it can reach Postgres
**So that** the platform restarts a dead process and a deploy is only called healthy when the database answers

**Acceptance criteria:**

- [x] `GET /health` answers 200 without touching any dependency, even when Postgres is unreachable (spec B-1).
- [x] `GET /health/ready` answers 200 when Postgres answers and 503 when it cannot connect (spec B-1).

**E2E test:** `e2e/health.spec.ts`
**Ticket:** IAN-124

## US-INFRA-002: Request IDs on every response and log line

**As** an operator debugging a failed request
**I want to** find every log line for one request by a single ID that the response also carries
**So that** a user's report or a trace can be joined to the server logs

**Acceptance criteria:**

- [x] A valid inbound `X-Request-Id` matching `^[A-Za-z0-9._-]{1,64}$` is echoed on the response (spec B-2).
- [x] An invalid or missing one is replaced by a new UUID (spec B-2).
- [x] Every log line emitted during the request carries the same ID (spec B-2).

**E2E test:** `e2e/health.spec.ts`
**Ticket:** IAN-124

## US-INFRA-003: Web server health check

**As** an operator running the web server on Railway
**I want to** probe whether the Nuxt server process is alive without it calling the backend
**So that** a web container is restarted only for its own failures, not for an API outage

**Acceptance criteria:**

- [x] `GET /api/health` on the Nuxt server answers 200 `{"status": "ok"}` without contacting the backend.

**E2E test:** `e2e/landing.spec.ts`
**Ticket:** IAN-125

## US-INFRA-004: Worker health probes

**As** an operator running the background worker on Railway
**I want to** probe whether the worker process is alive, and separately whether it can reach Postgres and Redis
**So that** a stuck worker is restarted, while a dependency outage shows as not ready without restarting a working process

**Acceptance criteria:**

- [x] `GET /health` on `WORKER_PORT` (default 3002) answers 200 `{"status": "ok"}` without touching Postgres or Redis, and the worker image's `HEALTHCHECK` calls it.
- [x] `GET /health/ready` answers 200 with `db` and `redis` both `connected` when both answer within 2 seconds, and 503 `degraded` naming each unreachable dependency otherwise.
- [x] The worker starts under arq with a five-minute `worker_heartbeat` log line as its only job until slice 04.
- [x] After losing Redis the worker exits, and the platform (or compose's restart policy) brings it back healthy once Redis returns.

**E2E test:** the `docker-build` CI job (`docker compose up --wait`, which waits on the worker's readiness), plus `apps/server/tests/integration/workers/test_health_redis.py` against a real Redis
**Ticket:** IAN-127

## US-INFRA-005: One error shape for every failure

**As** a developer writing a client against this API
**I want to** handle every failure by switching on one machine-readable code in one body shape
**So that** I never parse a message, and a new endpoint's errors need no new client code

**Acceptance criteria:**

- [x] An unknown path answers 404 `ROUTING_NOT_FOUND` and the body never repeats the requested path (spec B-5).
- [x] A wrong method answers 405 `ROUTING_METHOD_NOT_ALLOWED`, and no error response carries FastAPI's default `detail` body (spec B-5).
- [x] A database failure during a request answers 503 `SERVER_DATABASE_UNAVAILABLE`, whether it arrives as SQLAlchemy's `OperationalError` or as the `DBAPIError` a connection lost mid-request is wrapped in (spec B-9). A refused connect is classified by `get_connection` from slice 02 PR 3 onward, rather than by a global handler on `builtins.ConnectionError`, so only a route that really opened a connection can report a database outage (IAN-169).
- [x] An unexpected error answers 500 with no traceback, and the exception's own message only outside production (spec B-9).
- [x] An invalid body answers 400 `INPUT_VALIDATION_ERROR` naming the offending field (R-406).
- [x] The 413 for an oversized body carries the same registry code rather than a local literal (spec B-43).
- [x] The envelope is declared in `openapi.yaml`, so `@repo/api-types` types it for the frontend.

**E2E test:** covered by unit tests in `apps/server/tests/unit/test_main_exception_handlers.py`; no new route ships in this PR, so no new e2e spec.
**Ticket:** IAN-168

## US-INFRA-006: A migrated schema and one transaction per request

**As** a developer building the first endpoints that store data
**I want to** deploy a schema through a reversible migration chain and write through one transaction per request
**So that** no process ever serves traffic against an unmigrated database, and a handler that fails partway leaves nothing behind

**Acceptance criteria:**

- [x] `alembic upgrade head` creates the shared `set_updated_at` trigger function, the `users` table, and the unique index on `lower(email)`; `alembic downgrade base` removes all three, so the first revision is reversible.
- [x] Updating a `users` row moves `updated_at` and leaves `created_at` unchanged, because the trigger fires on every update.
- [x] Two addresses differing only in case cannot both be stored, so a mixed-case duplicate is a duplicate at registration in slice 03.
- [x] A route declaring `Depends(get_connection, scope="function")` commits when it returns and rolls back when it raises, and a commit that itself fails changes the response rather than following a success the client already holds.
- [x] A route taking that dependency while Postgres is unreachable answers 503 `SERVER_DATABASE_UNAVAILABLE`, and a route raising an unrelated socket error answers 500 (IAN-169).
- [x] The API image carries `alembic.ini` and `migrations/`, and the compose `migrate` service runs `alembic upgrade head` on that image before `api` and `worker` start, through `condition: service_completed_successfully`.
- [x] The integration suite and the end-to-end suite both reach head through that same one-shot service or the same Alembic chain, so no suite invents a schema of its own.

**E2E test:** `e2e/global-setup.ts` runs the migration the whole end-to-end suite then depends on; the behavior itself is covered by `apps/server/tests/integration/db/`, because no user-facing route reads the table until slice 03.
**Ticket:** IAN-169

## US-INFRA-007: Protections in place before the first public route

**As** an operator exposing this API to the internet
**I want to** know that every response is hardened, that a foreign origin cannot drive a signed-in browser, and that no request can occupy a worker indefinitely
**So that** slice 03's public login route arrives behind these protections rather than having them retrofitted after it ships

**Acceptance criteria:**

- [x] Every response carries `X-Content-Type-Options: nosniff` and a `Referrer-Policy`, rejections included, and `Strict-Transport-Security` is sent only under production (spec B-35).
- [x] A preflight from the configured `CORS_ORIGIN` is allowed with credentials, and a preflight from any other origin receives no `Access-Control-Allow-Origin` header at all (spec B-35).
- [x] A state-changing request without `X-Requested-With: XMLHttpRequest` answers 403 `CSRF_HEADER_MISSING` in the error envelope; the same request with the header reaches the handler; a safe method is never checked (spec B-6).
- [x] The CSRF exemptions are the two health routes and the Stripe webhook, matched by exact path, so a path merely sharing a prefix with an exempt one is still guarded (spec B-6).
- [x] A handler running past 30 seconds is cancelled, not merely abandoned, and answers 408 `SERVER_REQUEST_TIMEOUT` (spec B-8).
- [x] A guard's rejection still carries the request ID header, the security headers, and a log line bound to the same request ID, which is what pins the middleware order.
- [x] Production refuses to start without `CORS_ORIGIN`, `REDIS_URL`, or `FORWARDED_ALLOW_IPS`, and the README's environment table lists all three.

**E2E test:** covered by unit tests in `apps/server/tests/unit/middleware/` and `apps/server/tests/unit/test_main_middleware_order.py`; no user-facing route ships in this PR, so no new e2e spec.
**Ticket:** IAN-170

## US-INFRA-008: A request budget a client cannot forge its way around

**As** an operator running a public API with a login route
**I want to** bound what any one client can spend, with a far tighter bound on the credential paths
**So that** credential guessing and simple abuse are limited before slice 03 exposes a login route, and no client can escape its budget by rewriting a header

**Acceptance criteria:**

- [x] The eleventh request inside the window to each of `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/forgot-password` and `/v1/auth/reset-password` answers 429 `RATE_LIMIT_EXCEEDED` with `Retry-After`, and the tenth does not (spec B-7).
- [x] The one hundred and first request of any kind answers 429, and `GET /v1/auth/me` counts against that bucket but never against the auth one (spec B-7).
- [x] Two distinct client addresses arriving through the proxy count in two buckets, a client prepending forged `X-Forwarded-For` entries is counted in its own bucket, and a request arriving directly is keyed on its peer address (spec B-7).
- [x] The health routes and the Stripe webhook are never rate limited, including after the global bucket is spent (spec B-7).
- [x] Counting is one atomic operation, so concurrent requests cannot all be admitted and no key is left without an expiry; the window is fixed rather than re-armed by each request.
- [x] Without Redis outside production the limiter counts in process and logs `rate_limiter_in_memory` exactly once; production never counts in process (spec B-46).
- [x] In production a Redis outage, whether the connection drops after a successful start or the first connection never succeeds, answers 503 `SERVER_RATE_LIMIT_UNAVAILABLE` on the four auth paths, serves every other route, and logs `rate_limiter_unavailable`.
- [x] Compose fixes the web service's address so `FORWARDED_ALLOW_IPS` names one proxy rather than Docker's whole private range, and the README records it.

**E2E test:** covered by integration tests in `apps/server/tests/integration/middleware/` against the real Redis, including the proxy-header and concurrency cases; no user-facing route ships in this PR, so no new e2e spec.
**Ticket:** IAN-171

## US-AUTH-001: A session store that survives a leak and a password change

**As** the owner of this template
**I want to** know that a stolen database gives up no live session, that a missing account costs an attacker the same as a wrong password, and that a password change actually revokes
**So that** the auth endpoints in the next pull request are built on primitives that are already correct rather than ones that look correct

**Acceptance criteria:**

- [x] `user_sessions` stores only the SHA-256 of the token its cookie carries, so the raw token exists nowhere but the client; deleting a user cascades to their sessions; and `expires_at` is indexed for the cleanup job slice 08 adds.
- [x] Passwords are hashed with bcrypt at cost 12, asserted by reading the cost out of the stored hash rather than from a constant, and every bcrypt call runs off the event loop.
- [x] `verify_password` contains no conditional at all: it resolves a comparison hash, compares once, and returns, so a missing user reaches the same comparison a wrong password does (spec B-11). A structural test pins this, because a value assertion alone passes against a short-circuit that never runs bcrypt.
- [x] `generate_session_token` returns the raw token and its SHA-256 together, and the raw token has the length and alphabet `secrets.token_urlsafe(32)` produces.
- [x] `lock_user_for_update` serializes two concurrent transactions on one user, observed through Postgres's own lock graph rather than inferred from elapsed time. This closes a race neither B-11 nor B-13 names, where a login verifying an old password can insert a live session after a password change has revoked every other one.
- [x] Email lookups trim and lowercase before comparing, and compare on `lower(email)` rather than with `ILIKE`, which would read an underscore in an address as a wildcard and would miss the functional unique index.
- [x] The session dependency tells an absent cookie and an unknown token (both `AUTH_REQUIRED`) from an expired session (`AUTH_SESSION_EXPIRED`), and returns the session id beside the user so a password change can preserve the caller's own session. A second, non-raising resolver serves logout, which must answer the same way whether or not a session existed (spec B-31).
- [x] `last_seen_at` moves at most once every five minutes, through a condition inside the UPDATE, so two simultaneous requests cannot both decide the row is stale and both write it.

**E2E test:** none in this pull request; no route reaches these primitives until slice 03 PR 2. Covered by `apps/server/tests/unit/core/test_security.py` and `apps/server/tests/integration/db/test_auth_primitives.py`.
**Ticket:** IAN-315

## US-AUTH-002: An account someone can actually sign in to

**As** a person using an application built from this template
**I want to** register, sign in, sign out, see who I am, and change my password
**So that** the account lifecycle exists end to end on the server before any page calls it

**Acceptance criteria:**

- [x] Registration stores a bcrypt hash whose cost reads as 12 out of the hash itself, stores the address trimmed and lowercased, and answers 409 `AUTH_EMAIL_ALREADY_REGISTERED` for a duplicate that differs only in case (spec B-10).
- [x] The session cookie is `HttpOnly`, `SameSite=Lax`, `Path=/`, carries the seven-day lifetime, and is `Secure` outside local development; each attribute is asserted separately, and the issued cookie's SHA-256 equals the stored `token_hash` (spec B-10).
- [x] A wrong password and an unknown address answer the same code, a correct sign-in writes a session row, a sign-in removes that user's expired sessions while leaving live ones, and a mixed-case, whitespace-padded address signs in (spec B-11).
- [x] Changing the password requires the current one, makes the old one stop working and the new one start, signs out every other session, and leaves the caller signed in (spec B-13).
- [x] Logging out answers 204 with or without a session, deletes the row, and clears the cookie, asserted on the `Set-Cookie` expiry rather than only by a later rejection (spec B-31).
- [x] `GET /v1/auth/me` answers the id and email, never a password hash, and 401 without a session (spec B-32).
- [x] A sign-in and a password change on one account, genuinely overlapping, cannot leave a session built on the retired password. Both take the user row lock before verifying anything.
- [x] A rejected body answers 400 `INPUT_VALIDATION_ERROR` carrying a structured list naming each offending field, which is what a form needs to show a message beside its input; the key is absent from every other failure.
- [x] Each handler has a negative-input test covering an oversized body, an injection string, and malformed encoding (R-406).

**E2E test:** `e2e/auth.spec.ts`, which drives the round trip against the running stack: register, identify, change the passphrase, prove the old one fails and the new one works, log out, and prove the cookie is dead. What it cannot see from outside the process, the bcrypt cost, the stored token hash, and row-level revocation, is covered by `apps/server/tests/integration/routers/auth/`.
**Ticket:** IAN-320

---

## US-AUTH-003: A signed-out visitor cannot reach a signed-in page

**As** a person using an application built from this template
**I want to** be sent to the sign-in page whenever I am not signed in, and kept out of the sign-in page when I am
**So that** the account the server already enforces is enforced by the pages as well, on a first load and on every navigation after it

**Acceptance criteria:**

- [ ] A signed-out browser asking for `/dashboard` lands on `/login`, whether it arrives by a full page load or by a client-side navigation (spec B-12).
- [ ] A session that expired while a tab sat open redirects on the next navigation rather than after the cache goes stale: the session gate revalidates on every client-side navigation instead of trusting a cached success, and the page's own readers reuse that answer rather than asking again. The test populates the cache with a valid session first, so it exercises revalidation rather than an empty cache.
- [ ] A backend outage is not treated as a sign-out. Only the status the backend actually answers with for an absent or expired session sends anyone to `/login`.
- [ ] A signed-in browser asking for `/login` or for `/register` is sent to `/dashboard`, both pages asserted, since a redirect applied to one and not the other is the likely mistake (spec B-45).
- [ ] The protected layout renders nothing until the session resolves, so a protected page never paints content for a visitor who turns out to be signed out.
- [ ] The Nitro gate is a presence check only: it never calls the backend, never parses the cookie, skips `/api/**` so a proxied call gets the backend's own 401 rather than a 302 to an HTML page, and never gates `/login` itself.
- [ ] Signing out removes the session from the query cache rather than invalidating it, so nothing refetches `GET /v1/auth/me` with a cookie that has just been cleared.
- [ ] Two concurrent server-side renders for two signed-in people each reach FastAPI with only their own cookie and their own address, neither is counted in the rate-limit bucket of the Nuxt server's own address, and each rendered page shows its own user (spec B-52).
- [ ] The browser's call reaches the backend with its query string intact, the `Set-Cookie` a sign-in answers with reaches the browser, and one request ID is shared by the page response and the backend call, for a missing and for an invalid inbound value (R-341).

**E2E test:** `e2e/authGate.spec.ts`
**Ticket:** IAN-328

## US-INFRA-009: Retry a request without doing it twice

**As** a client of the API
**I want to** retry a `POST` or `PUT` with the same `Idempotency-Key` and get the first answer back
**So that** a network failure never makes me charge, create, or send something twice

**Acceptance criteria:**

- [x] A repeated request with the same key from the same user within 24 hours replays the stored status and body without running the handler (spec B-17).
- [x] A handler that fails releases its claim, so the retry runs again rather than answering 409 (spec B-18).
- [x] Reusing a key for a different method, path, or body answers 422 `IDEMPOTENCY_KEY_REUSED` and runs no handler (spec B-40).
- [x] Two simultaneous requests with one key run the handler once, and a claim left past its 60-second lease is taken over exactly once (spec B-44).
- [x] A late completion or release by a request that was taken over changes nothing (spec B-53).

**E2E test:** exercised through the test-only router in `apps/server/tests/integration/middleware/idempotency/`; the first real replayable route is slice 06's checkout.
**Ticket:** IAN-336

## US-INFRA-010: Prove every service starts and answers, and deploy it from committed configuration

**As** the owner of a fork about to deploy it
**I want to** run one command that proves every service started and answers, and to find each service's Railway configuration already in the repository
**So that** the first deploy is configuration rather than discovery, and CI has already proved the production images serve

**Acceptance criteria:**

- [x] `pnpm smoke` checks the web server's `/api/health`, the API's `/health` and `/health/ready`, the worker's `/health/ready`, and the landing page, against the compose ports by default and against any deployment through `SMOKE_WEB_URL`, `SMOKE_API_URL`, and `SMOKE_WORKER_URL`.
- [x] CI's `e2e` job runs the smoke suite against the compose stack built from the production images (spec B-28, amended 2026-09-24: the template itself is never deployed).
- [x] Each of the three services has a committed Railway config naming its Dockerfile and a healthcheck path the code actually serves, and only the API's config runs `alembic upgrade head` before deploying; a unit test holds each of these against the code.
- [x] The README's deploy section lists every variable each service needs, and no config file holds a variable or a secret.

**E2E test:** `e2e/smoke/services.smoke.ts` (the smoke suite); `apps/server/tests/unit/deploy/test_railway_config.py` for the configuration
**Ticket:** IAN-341

## US-INFRA-011: Every page is usable with a screen reader, a keyboard, and reduced motion

**As** a visitor who uses a screen reader, navigates by keyboard, or has asked the system to reduce motion
**I want to** use every page of the application in the way I browse
**So that** no page shuts me out or makes me unwell

**Acceptance criteria:**

- [x] Lighthouse's accessibility category scores 100 on the landing, log-in, register, forgot-password, reset-password, dashboard, and admin pages, the last two signed in as an admin (spec B-27).
- [x] Tab reaches every focusable control on each of those pages, each control paints a visible focus indicator, and a form submits from the keyboard alone (spec B-48).
- [x] With `prefers-reduced-motion: reduce`, nothing animates on any of those pages while each control is hovered and focused (spec B-48).
- [x] The error color meets 4.5:1 contrast on every surface, and a link standing on its own line on the auth pages has a 24-pixel target (the two failures the first Lighthouse run found).

**E2E test:** `e2e/accessibility.spec.ts`
**Ticket:** IAN-341

## US-INFRA-012: Expired rows are cleaned up without anyone scheduling it

**As** the owner of a fork running it in production
**I want to** have expired sessions, spent idempotency keys, and old webhook ledger rows deleted on a schedule the worker already runs
**So that** those tables stay the size of their live data, with no pg_cron extension to install and no second code path to keep in step

**Acceptance criteria:**

- [x] The worker registers `delete_expired_rows` as an arq cron job that runs at minute 0 of every hour and not at startup.
- [x] One run deletes every `user_sessions` row whose `expires_at` has passed, every `request_idempotency_keys` row older than 24 hours, and every `billing_webhook_events` row last attempted more than 30 days ago, and leaves every unexpired row in place (spec B-26).
- [x] Each table is cleared in batches of 1000, each batch in its own short transaction, until a batch deletes fewer than 1000, so a backlog larger than one batch is cleared in one run; each batch finds its rows through the index the table's migration already created.
- [x] A second run straight after the first deletes nothing.
- [x] The run logs one `expired_rows_deleted` line per table with its `deleted_count`, carrying the arq `job_id` (R-341).

**E2E test:** none, because a cron job has no page or route; covered by `apps/server/tests/integration/workers/test_delete_expired_rows.py` against real Postgres and the registration test in `apps/server/tests/unit/workers/test_worker_settings.py`
**Ticket:** IAN-341
