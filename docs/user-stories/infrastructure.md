# Infrastructure User Stories

## US-INFRA-001: Liveness and readiness endpoints

**As** an operator running the API on Railway
**I want to** probe whether the process is alive and whether it can reach Postgres
**So that** the platform restarts a dead process and a deploy is only called healthy when the database answers

**Acceptance criteria:**

- [ ] `GET /health` answers 200 without touching any dependency, even when Postgres is unreachable (spec B-1).
- [ ] `GET /health/ready` answers 200 when Postgres answers and 503 when it cannot connect (spec B-1).

**E2E test:** `e2e/health.spec.ts`
**Ticket:** IAN-124

## US-INFRA-002: Request IDs on every response and log line

**As** an operator debugging a failed request
**I want to** find every log line for one request by a single ID that the response also carries
**So that** a user's report or a trace can be joined to the server logs

**Acceptance criteria:**

- [ ] A valid inbound `X-Request-Id` matching `^[A-Za-z0-9._-]{1,64}$` is echoed on the response (spec B-2).
- [ ] An invalid or missing one is replaced by a new UUID (spec B-2).
- [ ] Every log line emitted during the request carries the same ID (spec B-2).

**E2E test:** `e2e/health.spec.ts`
**Ticket:** IAN-124

## US-INFRA-003: Web server health check

**As** an operator running the web server on Railway
**I want to** probe whether the Nuxt server process is alive without it calling the backend
**So that** a web container is restarted only for its own failures, not for an API outage

**Acceptance criteria:**

- [ ] `GET /api/health` on the Nuxt server answers 200 `{"status": "ok"}` without contacting the backend.

**E2E test:** `e2e/landing.spec.ts`
**Ticket:** IAN-125
