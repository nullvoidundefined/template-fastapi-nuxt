# template-fastapi-nuxt Feature List

Status key: **Complete** | **Partial** | **Planned**

Last updated: 2026-09-20 (slice 02 PR 2: the error envelope)

<!--
R-607: one `## <Area>` section per product area, each holding one table.
One row per feature: its status and notes that name the covering story ids
(US-<AREA>-NNN). feature-create inserts a Planned row at feature start;
task-cleanup moves it to Complete, or to Partial with the gap in the notes,
when the feature closes. Rewrite the Last updated line on every change, with
the date and what changed. Section shape:

## <Area>

| Feature | Status | Notes |
| ------- | ------ | ----- |
| <feature> | **Planned** | US-<AREA>-001 |
-->

---

## Infrastructure

| Feature                                                                                                 | Status       | Notes                                                                                  |
| ------------------------------------------------------------------------------------------------------- | ------------ | -------------------------------------------------------------------------------------- |
| Liveness and readiness endpoints (`GET /health`, `GET /health/ready`)                                   | **Complete** | US-INFRA-001; spec B-1; PR #6, with `e2e/health.spec.ts` in CI since PR #10            |
| Request IDs on every response and log line                                                              | **Complete** | US-INFRA-002; spec B-2; PR #6, with `e2e/health.spec.ts` in CI since PR #10            |
| Web server health check (`GET /api/health` on the Nuxt server)                                          | **Complete** | US-INFRA-003; PR #7, with `e2e/landing.spec.ts` in CI since PR #10                     |
| API type contract: OpenAPI export, generated `@repo/api-types`, typed client, drift check               | **Complete** | spec B-4; PR #9, and CI's `openapi-drift` job since PR #10                             |
| Worker health probes (`GET /health`, `GET /health/ready` on `WORKER_PORT`) and a five-minute heartbeat  | **Complete** | US-INFRA-004; spec B-3 and R-345; unit tests plus a real-Redis integration test        |
| Containers and CI: three images, compose with Postgres 17 and Redis 7, the seven-job CI graph, lefthook | **Complete** | spec B-3; PR #10; every job green on `main`                                            |
| Error envelope: `{ code, error }` on every failure, a code registry, and five exception handlers        | **Complete** | US-INFRA-005; spec B-5, B-9, B-43; typed into `@repo/api-types` through `openapi.yaml` |

## Landing

| Feature                                        | Status       | Notes                                                                                         |
| ---------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------- |
| Landing page with links to log in and register | **Complete** | US-LANDING-001; spec B-49; PR #7; the log-in and register pages themselves arrive in slice 03 |
