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
