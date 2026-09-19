# template-fastapi-nuxt Feature List

Status key: **Complete** | **Partial** | **Planned**

Last updated: 2026-09-19 (slice 01 PR 4)

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

| Feature                                                                                                 | Status       | Notes                                                                                                      |
| ------------------------------------------------------------------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------- |
| Liveness and readiness endpoints (`GET /health`, `GET /health/ready`)                                   | **Partial**  | US-INFRA-001; spec B-1; shipped in PR #6, e2e runs once PR 4 adds Playwright                               |
| Request IDs on every response and log line                                                              | **Partial**  | US-INFRA-002; spec B-2; shipped in PR #6, e2e runs once PR 4 adds Playwright                               |
| Web server health check (`GET /api/health` on the Nuxt server)                                          | **Partial**  | US-INFRA-003; shipped in PR #7, e2e runs once PR 4 adds Playwright                                         |
| API type contract: OpenAPI export, generated `@repo/api-types`, typed client, drift check               | **Partial**  | spec B-4; `pnpm check:contract` runs locally, CI's `openapi-drift` job arrives in PR 4                     |
| Worker health probes (`GET /health`, `GET /health/ready` on `WORKER_PORT`) and a five-minute heartbeat  | **Complete** | spec B-3 and R-345; unit tests plus a real-Redis integration test                                          |
| Containers and CI: three images, compose with Postgres 17 and Redis 7, the seven-job CI graph, lefthook | **Partial**  | spec B-3; every container reports healthy locally, and the first CI run on this branch proves the pipeline |

## Landing

| Feature                                        | Status      | Notes                     |
| ---------------------------------------------- | ----------- | ------------------------- |
| Landing page with links to log in and register | **Planned** | US-LANDING-001; spec B-49 |
