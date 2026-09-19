# template-fastapi-nuxt Feature List

Status key: **Complete** | **Partial** | **Planned**

Last updated: 2026-09-19 (slice 01 PR 2: landing page and web health check planned)

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

| Feature | Status | Notes |
| ------- | ------ | ----- |
| Liveness and readiness endpoints (`GET /health`, `GET /health/ready`) | **Planned** | US-INFRA-001; spec B-1 |
| Request IDs on every response and log line | **Planned** | US-INFRA-002; spec B-2 |
| Web server health check (`GET /api/health` on the Nuxt server) | **Planned** | US-INFRA-003 |

## Landing

| Feature | Status | Notes |
| ------- | ------ | ----- |
| Landing page with links to log in and register | **Planned** | US-LANDING-001; spec B-49 |
