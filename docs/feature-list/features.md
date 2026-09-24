# template-fastapi-nuxt Feature List

Status key: **Complete** | **Partial** | **Planned**

Last updated: 2026-09-24 (slice 04: password reset end to end)

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

| Feature                                                                                                 | Status       | Notes                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Liveness and readiness endpoints (`GET /health`, `GET /health/ready`)                                   | **Complete** | US-INFRA-001; spec B-1; PR #6, with `e2e/health.spec.ts` in CI since PR #10                                                                                     |
| Request IDs on every response and log line                                                              | **Complete** | US-INFRA-002; spec B-2; PR #6, with `e2e/health.spec.ts` in CI since PR #10                                                                                     |
| Web server health check (`GET /api/health` on the Nuxt server)                                          | **Complete** | US-INFRA-003; PR #7, with `e2e/landing.spec.ts` in CI since PR #10                                                                                              |
| API type contract: OpenAPI export, generated `@repo/api-types`, typed client, drift check               | **Complete** | spec B-4; PR #9, and CI's `openapi-drift` job since PR #10                                                                                                      |
| Worker health probes (`GET /health`, `GET /health/ready` on `WORKER_PORT`) and a five-minute heartbeat  | **Complete** | US-INFRA-004; spec B-3 and R-345; unit tests plus a real-Redis integration test                                                                                 |
| Containers and CI: three images, compose with Postgres 17 and Redis 7, the seven-job CI graph, lefthook | **Complete** | spec B-3; PR #10; every job green on `main`                                                                                                                     |
| Error envelope: `{ code, error }` on every failure, a code registry, and five exception handlers        | **Complete** | US-INFRA-005; spec B-5, B-9, B-43; typed into `@repo/api-types` through `openapi.yaml`                                                                          |
| Schema and migrations: Alembic, the `users` table, and one transaction per request                      | **Complete** | US-INFRA-006; slice 02 PR 3, enabling slice 03's storage rather than an acceptance criterion of its own; the compose `migrate` service gates `api` and `worker` |
| Request protections: security headers, CORS, the CSRF header guard, and a 30 second timeout             | **Complete** | US-INFRA-007; spec B-6, B-8, B-35; production refuses to start without CORS_ORIGIN                                                                              |
| Rate limiting: two shared budgets counted atomically in Redis, keyed on the resolved client             | **Complete** | US-INFRA-008; spec B-7, B-46; production fails the auth paths closed when Redis is gone                                                                         |
| Session store and password primitives: `user_sessions`, bcrypt at cost 12, the cookie resolver          | **Complete** | US-AUTH-001; consumed by the endpoints in slice 03 PR 2                                                                                                         |
| Auth endpoints: register, log in, log out, read and change the signed-in user                           | **Complete** | US-AUTH-002; spec B-10, B-11, B-13, B-31, B-32; the pages that call them shipped                                                                                |
| Field-level validation errors on the error envelope                                                     | **Complete** | US-AUTH-002; what B-38 needs in slice 03 PR 4; the key is absent from every other failure                                                                       |
| Session query layer: one query client per request, SSR hydration, and typed route wrappers              | **Complete** | US-AUTH-003; a failed request becomes a failed query rather than a resolved one holding an error                                                                |
| Nitro API proxy and per-request IDs on page requests                                                    | **Complete** | US-AUTH-003; the query string survives, `Set-Cookie` propagates, and the forwarded chain is replaced by the edge-appended address                               |
| Auth gate: the Nitro presence check, the route middleware, and the protected layout                     | **Complete** | US-AUTH-003; spec B-12, B-45; the gate revalidates on every navigation and treats an outage as an error rather than a sign-out                                  |
| Nitro proxy, per-request query client, and request ID shared by page and API                            | **Complete** | US-AUTH-003; spec B-52                                                                                                                                          |
| Auth gate: server cookie gate, client revalidating middleware, protected and auth layouts               | **Complete** | US-AUTH-003; spec B-12, B-45                                                                                                                                    |
| UI kit: Button, Modal, Toast, TextField with Storybook stories and a visual-regression CI job           | **Complete** | US-AUTH-004; spec B-39, B-48                                                                                                                                    |
| Register, log-in and dashboard password-change forms with field-level errors                            | **Complete** | US-AUTH-004; spec B-38, B-50                                                                                                                                    |
| Password reset: `user_password_resets`, the forgot and reset endpoints, and the arq email job           | **Partial**  | spec B-14, B-15, B-47; the backend is done (Resend client, `with_client_telemetry`, retries); the two pages (B-36) arrive in the slice 04 frontend half         |

## Landing

| Feature                                        | Status       | Notes                                                                               |
| ---------------------------------------------- | ------------ | ----------------------------------------------------------------------------------- |
| Landing page with links to log in and register | **Complete** | US-LANDING-001; spec B-49; PR #7; the log-in and register pages shipped in slice 03 |
