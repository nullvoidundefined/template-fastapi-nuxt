# Slice 02: Data and Errors

Spec: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md` (acceptance criteria B-5 to B-9, B-35, B-43, B-46)
Status: Gate 1 approved by the owner on 2026-09-20; PR 1 in progress
Tracker: IAN-166 (Linear project template-fastapi-nuxt), with IAN-167 to IAN-171 one per PR (R-605)
Estimate: 4 hours of agent time across five PRs, of which 50 minutes is the slice-01 Later list carried in here as PR 1. The estimate is the R-906 heuristic rather than history: this project has four closed standard llm tickets carrying actuals, below the five-sample floor.

## Purpose

Slice 01 proved the pipeline: an app that starts, a page that renders, a type contract, three images, and a green CI graph. Nothing in it touches the database, and every error it can produce still comes out in FastAPI's default shape rather than the template's own. This slice closes both gaps, so that slice 03's auth endpoints have somewhere to store a user, a way to fail in the envelope every client already expects, and the protections that a public authentication route needs from its first commit rather than as a later hardening pass.

Three things land here. The error envelope and its five exception handlers make every failure, expected or not, answer with `{ code, error }` and a code from the registry. Alembic, the `users` table, and the per-request connection dependency give the application its first data access. The remaining middleware (security headers, CORS, the CSRF header guard, the request timeout, and the rate limiter) complete the pure ASGI stack that the spec's backend feature map fixes, leaving only slice 05's idempotency middleware to come.

The slice also closes the two items the slice-01 Later list assigned to slice 02: root ESLint coverage and a Docker build cache in CI. Both are CI chores rather than acceptance criteria, and they land first so that every later PR in the slice is reviewed under the stronger lint and a faster build.

## Scope note: the auth paths do not exist yet

B-6 and B-7 describe behavior on routes that arrive in slice 03, and B-7's rate-limit buckets name four auth paths by their full path. As the spec's slice plan says, these criteria are exercised through a test-only router that only the test application factory mounts. The middleware matches on the path it sees, so a test-only route mounted at `/v1/auth/login` exercises the same branch the real route will take in slice 03, and the real routes then carry the same behavior in their own slice's end-to-end tests. No test-only route is ever mounted by `create_app()`.

## How every PR in this slice is built

- **Tests are written by Codex**, OpenAI's coding agent run through its command-line interface, from the acceptance criteria and the PR's description, before any implementation exists (R-907, owner decision 2026-09-19). Claude's `test-author` subagent writes a test only when Codex is unavailable or rate-limited, and the PR and this document record that. Codex was at its ChatGPT usage limit until 2026-09-21 02:26 local when this plan was written, so the first PRs of this slice may take the recorded fallback.
- **Implementation follows the red, green, refactor cycle** under the harness's slice lock (R-412), through `enforce/tdd.sh`.
- **Before merge**, Codex reviews the PR's diff against the spec and this document's PR block, with a fresh Claude agent on an equal or stronger model as the recorded fallback (R-517). Every finding is fixed or answered with a reason, and the PR body carries a `## Codex review` section. Copilot review is never requested (R-514).
- **Gate 2:** the owner reviews and merges each PR on GitHub.
- **Documentation:** each PR writes its `docs/prs/2026-09-20-<slug>.md` before it opens, and the PRs that change behavior an operator or a user can observe add their row to `docs/feature-list/features.md` and their story to `docs/user-stories/infrastructure.md` (R-607).

## Execution record

| PR  | Concern                                    | Ticket  | PR number | Merged | Scope change                                                                                                                                                                                                                                                                                                                                                    |
| --- | ------------------------------------------ | ------- | --------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | CI hardening: root lint and a build cache  | IAN-167 | #22       |        | The build cache is scoped per image rather than per job: both jobs build byte-identical images, so a per-job scope stores two copies and lets neither read the other's previous run. The pre-merge review also found that flat config does not skip dot-directories, so `.claude/` had to be ignored or a checkout holding a worktree would lint that copy too. |
| 2   | The error envelope and its five handlers   | IAN-168 | pending   |        |                                                                                                                                                                                                                                                                                                                                                                 |
| 3   | Alembic, `users`, and the connection       | IAN-169 | pending   |        |                                                                                                                                                                                                                                                                                                                                                                 |
| 4   | Security headers, CORS, CSRF, and timeout  | IAN-170 | pending   |        |                                                                                                                                                                                                                                                                                                                                                                 |
| 5   | Rate limiting and the Redis settings guard | IAN-171 | pending   |        |                                                                                                                                                                                                                                                                                                                                                                 |

## PRs

### PR 1: CI hardening, root lint coverage and a Docker build cache

**Context:** Slice 01 is merged and the full CI graph is green on `main`. Two items on its Later list were deferred to this slice, and neither depends on anything else in it.

**Problem:** Only the `@repo/web` package runs ESLint today, so `e2e/`, `packages/tokens`, and the root configuration files are unlinted in CI and at commit; a lint rule that exists cannot catch what it never reads. Separately, the `docker-build` and `e2e` jobs each build all three images from scratch on every run, which is the slowest pair of jobs in the graph and will be paid on all four remaining PRs of this slice.

**Approach:** Add a root ESLint flat configuration that covers `e2e/`, `packages/`, and the root TypeScript and configuration files, and a root `lint` script that runs it alongside the existing per-package scripts. The web package keeps its own Nuxt-aware configuration, because the Nuxt ESLint integration generates rules from the app's own routes and layers, and flattening the two into one configuration would lose that.

Add `docker/setup-buildx-action` with the GitHub Actions cache backend to the `docker-build` and `e2e` jobs, so the layers of the three images are restored between runs instead of rebuilt. The cache is scoped per image, shared by both jobs: they build byte-identical images from the same commit, so one scope per image lets whichever job runs second read the entries the previous run wrote, and the repository's cache is not spent on two copies of the same layers.

**Contents:** `eslint.config.mjs` at the repository root, its dependencies in the root `package.json`, the root `lint` script, the lint job's new step in `.github/workflows/ci.yml`, the buildx setup and cache configuration in the `docker-build` and `e2e` jobs, and the lefthook entry that lints the newly covered paths at commit.

**Tests:** CI is the test for this PR: the `lint` job fails on a deliberate violation introduced in `e2e/` and removed before the PR opens, and the `docker-build` and `e2e` jobs report a cache hit on a second run of the same commit. No unit test is written for configuration that only CI executes, and the PR body records that reasoning rather than leaving it implicit.

**Review focus:** That the root configuration does not shadow or weaken the web package's Nuxt rules, and that the build cache is keyed so a changed Dockerfile still rebuilds the layers below it rather than serving a stale image to the end-to-end suite.

**Size:** About 6 files and 120 lines.

**Estimate:** 50 minutes (IAN-167).

### PR 2: The error envelope and its five exception handlers

**Context:** PR 1 has landed. The application answers only the two health routes, and any other path produces FastAPI's default `{ detail }` body.

**Problem:** B-5 and B-9 require that no response ever uses FastAPI's default error shape, and every later slice raises errors that clients switch on by code. The registry and the handlers must exist before the first real route, or slice 03's auth endpoints would each invent their own failure shape and be rewritten afterwards. The 100 KB body guard shipped in slice 01 already writes the envelope by hand, with its code and message as local string constants, and that duplication is resolved here rather than allowed to spread.

**Approach:** Add `app/constants/error_codes.py` with the `ErrorCode` string enum the Python track fixes, each member carrying a one-line comment saying when it fires, including `SERVER_RATE_LIMIT_UNAVAILABLE`, which PR 5 raises when Redis is lost in production. Add `app/errors.py` with `AppError(status_code, code, message)` and the `NotFoundError`, `ConflictError`, and `ForbiddenError` subclasses that routes and services raise from slice 03 onward.

Add `register_exception_handlers` to `app/main.py` beside the factory, where the track places every `register_*` function, installing the five handlers it specifies: `AppError` to its own status and code; Starlette's `HTTPException` to `ROUTING_NOT_FOUND` or `ROUTING_METHOD_NOT_ALLOWED`, with a fixed message that never echoes the requested path; `RequestValidationError` to 400 `INPUT_VALIDATION_ERROR` with its field errors; the connection-class `OperationalError` and asyncpg's connection errors to 503 `SERVER_DATABASE_UNAVAILABLE`, widened to the exception types a real failed connect actually raises (slice 01's readiness route catches `OSError` alongside `SQLAlchemyError`, which is evidence that an asyncpg connect failure can arrive as neither of the two the track names, and an uncovered type would fall through to the 500 handler); and bare `Exception` to 500 `SERVER_INTERNAL_ERROR`. The 500 handler logs with `exc_info` and returns a fixed message in production, and the exception's own message outside production, never a traceback in either.

Handlers are registered after middleware and before the routers, which is the order the Python track requires and the order in which a handler's response still passes back out through the middleware that must decorate it.

Re-home the body-size guard's constants: `app/middleware/request_context.py` stops defining `PAYLOAD_TOO_LARGE_CODE` and its message and takes both from the registry and a shared envelope builder. Its behavior does not change, so its existing tests keep passing unchanged, which is the evidence that the refactor is behavior-preserving.

Because the envelope becomes a documented response shape, `app/schemas/errors.py` declares it as a Pydantic model and the routers reference it, so it appears in `openapi.yaml` and reaches `@repo/api-types` through the existing drift check rather than being a shape the frontend knows only by convention.

**Contents:** `app/constants/error_codes.py`, `app/errors.py`, `register_exception_handlers` in `app/main.py`, `app/schemas/errors.py`, the constant removal in `app/middleware/request_context.py`, the regenerated `apps/server/docs/openapi.yaml` and `packages/api-types/src/schema.ts`, the test application factory fixture in `apps/server/tests/conftest.py` and the test-only router it mounts (neither exists yet: today's `server_app` fixture calls `create_app()` directly), tests under `apps/server/tests/unit/`, and the R-607 feature row and `US-INFRA-005` story for the error envelope.

**Tests:** B-5: an unknown path answers 404 `ROUTING_NOT_FOUND` with a message that does not contain the requested path, including a path containing a marker string the assertion searches the body for, and a wrong method on a real route answers 405 `ROUTING_METHOD_NOT_ALLOWED`; neither body carries a `detail` key. B-9: a test-only route that raises `OperationalError` answers 503 `SERVER_DATABASE_UNAVAILABLE`, and one that raises an unexpected exception answers 500 whose body contains neither a traceback nor the exception message under `environment="production"`, while the message is present under `environment="development"`. B-43: the existing body-limit tests pass unchanged, and one new assertion reads the code from the registry rather than from a literal.

**Review focus:** The 500 handler. That it logs the exception with `exc_info` before answering, that nothing derived from the exception reaches the production response body, and that it cannot itself raise while building the envelope, since a handler that fails leaves the client with a bare ASGI error and no request ID.

**Size:** About 12 files and 400 lines.

**Estimate:** 45 minutes (IAN-168).

### PR 3: Alembic, the users table, and the connection dependency

**Context:** PRs 1 and 2 have landed. The engine is created at startup and disposed at shutdown, and readiness opens its own connection, but no request has a connection and no table exists.

**Problem:** Slice 03 stores users and sessions, and it cannot begin until there is a migration chain to add tables to, a `users` table to write to, and a per-request connection with a transaction boundary that a repository can take as a dependency. The `set_updated_at` trigger belongs to this first revision because every table that follows reuses it.

**Approach:** Add Alembic (the migration tool the Python track mandates) as `alembic.ini` and `migrations/`, with `migrations/env.py` importing the metadata from `app/db/tables.py` as `target_metadata` and running through the async engine. Add the first revision: the `set_updated_at` trigger function, the `users` table with `id`, `email`, `password_hash`, `created_at`, and `updated_at`, the unique index on `lower(email)` that makes a mixed-case duplicate a duplicate in slice 03, and the trigger attached to `users`. The `role` column is deliberately absent, because the data model assigns it to slice 05.

Write `upgrade()` and `downgrade()` by hand rather than shipping the autogenerated draft, since neither the trigger function, the functional unique index, nor the trigger itself is something autogeneration produces correctly.

Add `get_connection` to `app/db/session.py`, the module the track's layout names for it, yielding one connection inside one transaction per request from the engine on application state, committing when the handler returns and rolling back when it raises. Every data-bearing route declares it as `Depends(get_connection, scope="function")`: under FastAPI's default request scope the exit code runs after the response is sent, so a failed commit would follow a 201 the client had already received. The health routes are the deliberate exception and keep the contract slice 01 gave them (B-1): `/health` touches no dependency at all, and `/health/ready` opens its own connection inside its own timeout, so injecting this dependency into either would break liveness or bypass readiness's bound. Repositories in later slices take this connection, so the transaction boundary is the request and no repository opens its own.

Running a migration takes three things the repository does not have yet, all of which land here. Alembic becomes a runtime dependency in `pyproject.toml` rather than a dev one, because the command runs in the deployed image; the API image copies `alembic.ini` and `migrations/` alongside `app/`, which it does not today and which the Python track's own Dockerfile section already prescribes; and compose gains a one-shot `migrate` service that runs `alembic upgrade head` on the API image, with `api` and `worker` depending on it through `condition: service_completed_successfully` so no process serves traffic against an unmigrated database.

That covers the three places migrations run before deployment: compose locally and in the `docker-build` and `e2e` jobs, the integration job's fixture, and the end-to-end suite's global setup, which invokes the same one-shot service. Railway's `preDeployCommand` is the deployed path and arrives in slice 08 with the first deploy, which is why the image has to carry the migrations rather than the compose file alone.

**Contents:** `apps/server/alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/<rev>_create_users_and_set_updated_at.py`, `app/db/tables.py`, `app/db/session.py`, the Alembic runtime dependency in `apps/server/pyproject.toml` with its `uv.lock` update, the two new `COPY` lines in `apps/server/Dockerfile`, the one-shot `migrate` service and the two `depends_on` conditions in `docker-compose.yml`, a new `globalSetup` in `playwright.config.ts`, which has none today, the integration fixture in `apps/server/tests/integration/conftest.py`, tests, and the R-607 feature row and `US-INFRA-006` story for the schema and migrations.

**Tests:** Integration, against the real Postgres that the CI job already provides: `alembic upgrade head` followed by `alembic downgrade base` leaves no `users` table and no `set_updated_at` function, proving the revision is reversible; an update to a `users` row moves `updated_at` and leaves `created_at` unchanged, proving the trigger fires; inserting two rows whose emails differ only in case violates the unique index. For the dependency: a test-only route that writes and then raises leaves no row, and one that writes and returns leaves exactly one, proving the transaction boundary in both directions; a commit that fails answers an error status rather than a success the client has already received, which is the assertion that fails if `scope="function"` is dropped; and a route depending on `get_connection` under the suite's unreachable-database fixture answers 503 `SERVER_DATABASE_UNAVAILABLE`, proving that a real outage reaches PR 2's handler rather than falling through to the 500. A unit test asserts the migration-defaults guard's form (R-328) holds for the new revision. The image itself is covered by the `docker-build` job rather than a unit test: the `migrate` service runs on the API image, so a missing dependency or a missing `COPY` fails the job before the stack reports healthy.

**Review focus:** The transaction boundary. That a handler raising after a partial write rolls back rather than committing, that the connection is released back to the pool on every path including cancellation, and that a failed connect surfaces as the `OperationalError` PR 2's handler maps to 503 rather than as an unhandled error.

**Size:** About 10 files and 350 lines.

**Estimate:** 50 minutes (IAN-169).

### PR 4: Security headers, CORS, the CSRF guard, and the request timeout

**Context:** PRs 1 to 3 have landed. The application has data access and a consistent error shape, and the middleware stack holds only the request-ID handling and the body-size limit.

**Problem:** B-6, B-8, and B-35 are the protections that must already be in place when slice 03 exposes a public login route. They are grouped into one PR because they are a single concern, the ordered ASGI chain, and because the order in which they wrap each other is the part worth reviewing once rather than three times.

**Approach:** Add three pure ASGI classes and configure Starlette's CORS middleware. The security-headers class sets `X-Content-Type-Options: nosniff` and `Referrer-Policy` on every response and adds `Strict-Transport-Security` only in production. CORS is restricted to `CORS_ORIGIN` with credentials allowed, so a preflight from any other origin receives no `Access-Control-Allow-Origin` header at all rather than a permissive one.

The CSRF guard rejects a state-changing request that carries no `X-Requested-With: XMLHttpRequest` header with 403 `CSRF_HEADER_MISSING`. The health routes and the Stripe webhook are exempt, the latter because Stripe cannot send the header and is authenticated by its signature instead. Safe methods are never checked. The frontend already sets this header as a base header on every client, which slice 01's PR 3 shipped, so nothing on the client changes here.

The timeout class cancels a handler that runs past 30 seconds and answers 408 `SERVER_REQUEST_TIMEOUT`.

Settings gain `cors_origin` and `forwarded_allow_ips` together with the track's `require_production_values` validator, which refuses to start in production without all three of `CORS_ORIGIN`, `REDIS_URL`, and `FORWARDED_ALLOW_IPS`. B-46 names only `REDIS_URL`, and the track requires all three; the spec says the track wins where they disagree, and the reason is B-7's own threat model, since a missing forwarded-allow-ips value keys every proxied request on the proxy's address and puts the whole site in one bucket.

Register the chain so the request passes it in the order the Python track fixes, which reads outermost inward as: the correlation ID (1a), the request context (1b), the security headers (2), CORS (3), the rate limiter that PR 5 adds (4), the timeout (5), and the CSRF guard (6), with slice 05's idempotency middleware innermost (7).

That is the runtime order, not the order the calls are written. Starlette wraps middleware outside in, so the layer added last runs first: `register_middleware` calls `add_middleware` in reverse, innermost first, from the CSRF guard up to the correlation ID, exactly as `app/main.py` already does today for its two layers and as the track's own code block shows. Writing the calls in the runtime order would invert the chain and put the request-context binding outside the guards, which is the failure this PR exists to avoid.

The request context stays immediately inside the correlation ID, where slice 01 put it and where the track requires it, for a reason the ordering test has to protect: the structlog binding of `request_id` lives in that class, so any guard registered outside it would log without the request ID and break B-2's requirement that every log line for a request carries the same one. Keeping it at 1b also means the 100 KB body limit runs before the guards rather than after them.

The correlation ID is outermost so that every response, a guard's rejection included, carries a request ID. The security headers sit above CORS so that they decorate rejections as well as successes. CORS precedes the guards so that a preflight is answered without being rejected by a guard it cannot satisfy. The CSRF guard is innermost of the three this PR adds, as the track orders it.

**Contents:** `app/middleware/security_headers.py`, `app/middleware/csrf_guard.py`, `app/middleware/request_timeout.py` (the track's names), the `cors_origin` and `forwarded_allow_ips` fields and the `require_production_values` validator in `app/core/settings.py`, the ordered `register_middleware` in `app/main.py`, the exempt-path constants in `app/constants/`, tests, and the R-607 feature row and `US-INFRA-007` story for the request protections.

**Tests:** B-35: every response carries `nosniff` and `Referrer-Policy`, `Strict-Transport-Security` is present under `environment="production"` and absent otherwise, and a preflight from an origin other than `CORS_ORIGIN` receives no `Access-Control-Allow-Origin` header. B-6: a `POST` to a test-only route without `X-Requested-With` answers 403 `CSRF_HEADER_MISSING`, the same request with the header reaches the handler, a `GET` without the header is never rejected, and both a health route and the webhook path are exempt. B-8: a test-only route that sleeps past the limit answers 408 `SERVER_REQUEST_TIMEOUT`, with the limit injected so the test does not wait 30 seconds. One ordering test asserts that a 403 from the CSRF guard still carries the request ID header and the security headers, and, because a header-only assertion passes under either order, that a log line emitted during that rejection carries `request_id`; that second assertion is what fails if the request context is ever moved out from 1b. The track's production validator gets one settings test per missing value: production refuses to start without `CORS_ORIGIN`, without `REDIS_URL`, or without `FORWARDED_ALLOW_IPS`.

**Review focus:** The order of registration and the exemption lists. An exemption matched by prefix rather than by exact path would exempt more than it names, and the ordering test is the only thing standing between a future reordering and a rejection that silently loses its headers.

**Size:** About 12 files and 400 lines.

**Estimate:** 40 minutes (IAN-170).

### PR 5: Rate limiting and the Redis settings guard

**Context:** PRs 1 to 4 have landed, and the middleware chain has a gap reserved for the rate limiter between CORS and the CSRF guard.

**Problem:** B-7 is the densest criterion in the slice and the one with a real attacker in its threat model: a limiter keyed on a header a client controls is not a limiter. B-46 belongs with it, because the limiter's behavior without Redis is exactly what those settings decide. Both land alone so that the review can be spent on the trust chain.

**Approach:** Add the rate-limit middleware, keyed on `request.client.host` as uvicorn resolves it under the `--proxy-headers` flag the Dockerfile already passes.

Narrowing `FORWARDED_ALLOW_IPS` takes one change compose does not have today. Uvicorn's allowlist is a list of addresses and CIDRs, never a service name, and compose's default network allocates container addresses dynamically, so there is no web service address to name. Compose therefore gains a user-defined network with a fixed subnet and a static IPv4 for the `web` service, and `FORWARDED_ALLOW_IPS` on the API narrows from Docker's whole private range to that one address. Without the static assignment the only two options are a guessed address, which silently breaks client-IP resolution, and the existing `172.16.0.0/12`, which trusts every container in the range; neither is a basis for B-7. Deployed, the same variable carries the web service's private-network address, which Railway does give a stable value. The middleware never parses `X-Forwarded-For` itself. That is the whole of the trust chain on the server side: Railway's edge appends the connecting address, the Nitro proxy forwards only that last entry through `resolveClientAddress`, which slice 01 shipped, and uvicorn honors the header only from Nitro, so a request arriving from anywhere else is keyed on its own peer address.

Two buckets, counted in Redis so that every replica shares them: 100 requests per 15 minutes globally, and 10 per 15 minutes on exactly `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/forgot-password`, and `/v1/auth/reset-password`, matched on the full path. Exceeding either answers 429 `RATE_LIMIT_EXCEEDED` with `Retry-After`. `GET /auth/me` is deliberately outside the auth bucket, because a signed-in page calls it on every navigation, and it still counts against the global one. The health routes and the webhook are exempt from both.

Add the settings validation B-46 requires: settings refuse to load when `environment="production"` and `REDIS_URL` is unset, so the failure is a startup error rather than a silently unlimited production. Under `environment="test"` without Redis the limiter counts in process and logs `rate_limiter_in_memory` exactly once, so the suite runs without Redis while the log line makes the degraded mode visible rather than invisible.

Losing Redis after a successful start is a separate branch, and production never takes the in-memory path, because a per-replica count multiplies the effective limit by the replica count and a client can reset it by reconnecting. In production the four auth paths fail closed on a Redis error and answer 503 `SERVER_RATE_LIMIT_UNAVAILABLE`, while every other route is served with one error log carrying `rate_limiter_unavailable`, so a Redis blip costs four endpoints rather than the API. The log line is the whole signal in this slice: Sentry arrives in slice 07 under B-30, and inventing a reporting abstraction here to be filled in later would be unused code (R-309). Slice 07 adds the report when the client exists, and the Later list carries it. The owner settled this on 2026-09-20 after the review found the behavior asserted in the review focus but defined nowhere; the spec's Failure modes section carries the same wording.

**Contents:** `app/middleware/rate_limit.py`, its in-memory counter, the bucket and exempt-path constants in `app/constants/`, the registration slot in `app/main.py`, a user-defined compose network with a fixed subnet and a static IPv4 for `web`, the narrowing of the API's existing `FORWARDED_ALLOW_IPS` from Docker's whole private range to that address (the Dockerfile already runs uvicorn with `--proxy-headers` and uvicorn reads that variable natively, so no flag is added and the spec's `TRUSTED_PROXY_IPS` name is not introduced), tests, and the R-607 feature row and `US-INFRA-008` story for rate limiting.

**Tests:** B-7, as integration tests against the real Redis the CI job already provides. The proxied cases cannot be driven through the suite's bare `httpx.ASGITransport`, which never runs uvicorn's proxy-header handling, so they wrap the app in `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(app, trusted_hosts=<proxy address>)` and set the transport's `client` to the proxy address, with the direct case using a different one. Without that wrapping the forged-header assertion would pass whether or not the limiter parsed the header, which is the failure mode this test exists to rule out. The cases: the eleventh request in the window to each of the four auth paths answers 429 with `Retry-After` while the tenth does not; the one hundred and first request of any kind answers 429; two distinct client addresses arriving through the proxy are counted in two buckets; a client that prepends forged `X-Forwarded-For` entries is counted in its own bucket rather than the forged one; a request reaching the application directly rather than through the proxy is keyed on its peer address; `GET /auth/me` does not count against the auth bucket but does count against the global one; and neither a health route nor the webhook ever receives a 429, including after the global limit is exhausted. B-46: settings raise under `environment="production"` with no `REDIS_URL`, and under `environment="test"` without Redis two requests share an in-memory count while `rate_limiter_in_memory` is logged exactly once across both. The post-startup outage, with a Redis client that connects and then raises: under `environment="production"` each of the four auth paths answers 503 `SERVER_RATE_LIMIT_UNAVAILABLE`, a non-auth route is served normally, `rate_limiter_unavailable` is logged, and no in-memory counter is consulted on any of them.

**Review focus:** The key derivation, end to end. That no code path reads `X-Forwarded-For` directly, that the forged-header test is driven through the proxy-header wrapper and so would actually fail if it did, and that the in-memory fallback cannot be reached under `environment="production"` by any route, including a Redis connection that drops after a successful startup, which the post-startup outage test now pins rather than leaving to inspection.

**Size:** About 12 files and 450 lines.

**Estimate:** 55 minutes (IAN-171).

## Later list

Raised during planning and deliberately deferred, so that scope does not widen inside the slice:

- **Slice 03, Nitro request ID:** Nitro middleware that mints an `X-Request-Id` when the page request carries none and echoes it on the page response, so every server-side API call is correlated with its page (R-341). Carried forward unchanged from the slice-01 Later list. Until it lands, a server-side render without an inbound ID reaches FastAPI, which mints its own.
- **Slice 03, worker startup tests:** no test asserts that the worker configures logging at startup or that it runs its two readiness checks concurrently. Raised by the PR 4 review of slice 01 as finding 10, and left for the slice that next changes the worker.
- **Slice 07, report the rate limiter's unavailability:** when the Sentry client lands under B-30, the production Redis-outage branch reports as well as logs. Slice 02 logs `rate_limiter_unavailable` and nothing more, because the client does not exist yet and a no-op abstraction written now would be unused code (R-309). Raised by the Copilot review of the fail-closed decision.
- **Slice 05, idempotency middleware:** the sixth ASGI class and the only remaining gap in the chain this slice completes, planned by the spec for slice 05 with `request_idempotency_keys`.
