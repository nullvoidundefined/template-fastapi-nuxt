# template-fastapi-nuxt Feature List

Status key: **Complete** | **Partial** | **Planned** | **Excluded**

Last updated: 2026-09-24 (slice 08: the hourly `delete_expired_rows` cleanup job is Complete)

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

| Feature                                                                                                 | Status       | Notes                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Liveness and readiness endpoints (`GET /health`, `GET /health/ready`)                                   | **Complete** | US-INFRA-001; spec B-1; PR #6, with `e2e/health.spec.ts` in CI since PR #10                                                                                                   |
| Request IDs on every response and log line                                                              | **Complete** | US-INFRA-002; spec B-2; PR #6, with `e2e/health.spec.ts` in CI since PR #10                                                                                                   |
| Web server health check (`GET /api/health` on the Nuxt server)                                          | **Complete** | US-INFRA-003; PR #7, with `e2e/landing.spec.ts` in CI since PR #10                                                                                                            |
| API type contract: OpenAPI export, generated `@repo/api-types`, typed client, drift check               | **Complete** | spec B-4; PR #9, and CI's `openapi-drift` job since PR #10                                                                                                                    |
| Worker health probes (`GET /health`, `GET /health/ready` on `WORKER_PORT`) and a five-minute heartbeat  | **Complete** | US-INFRA-004; spec B-3 and R-345; unit tests plus a real-Redis integration test                                                                                               |
| Containers and CI: three images, compose with Postgres 17 and Redis 7, the seven-job CI graph, lefthook | **Complete** | spec B-3; PR #10; every job green on `main`                                                                                                                                   |
| Error envelope: `{ code, error }` on every failure, a code registry, and five exception handlers        | **Complete** | US-INFRA-005; spec B-5, B-9, B-43; typed into `@repo/api-types` through `openapi.yaml`                                                                                        |
| Schema and migrations: Alembic, the `users` table, and one transaction per request                      | **Complete** | US-INFRA-006; slice 02 PR 3, enabling slice 03's storage rather than an acceptance criterion of its own; the compose `migrate` service gates `api` and `worker`               |
| Request protections: security headers, CORS, the CSRF header guard, and a 30 second timeout             | **Complete** | US-INFRA-007; spec B-6, B-8, B-35; production refuses to start without CORS_ORIGIN                                                                                            |
| Rate limiting: two shared budgets counted atomically in Redis, keyed on the resolved client             | **Complete** | US-INFRA-008; spec B-7, B-46; production fails the auth paths closed when Redis is gone                                                                                       |
| Session store and password primitives: `user_sessions`, bcrypt at cost 12, the cookie resolver          | **Complete** | US-AUTH-001; consumed by the endpoints in slice 03 PR 2                                                                                                                       |
| Auth endpoints: register, log in, log out, read and change the signed-in user                           | **Complete** | US-AUTH-002; spec B-10, B-11, B-13, B-31, B-32; the pages that call them shipped                                                                                              |
| Field-level validation errors on the error envelope                                                     | **Complete** | US-AUTH-002; what B-38 needs in slice 03 PR 4; the key is absent from every other failure                                                                                     |
| Session query layer: one query client per request, SSR hydration, and typed route wrappers              | **Complete** | US-AUTH-003; a failed request becomes a failed query rather than a resolved one holding an error                                                                              |
| Nitro API proxy and per-request IDs on page requests                                                    | **Complete** | US-AUTH-003; the query string survives, `Set-Cookie` propagates, and the forwarded chain is replaced by the edge-appended address                                             |
| Auth gate: the Nitro presence check, the route middleware, and the protected layout                     | **Complete** | US-AUTH-003; spec B-12, B-45; the gate revalidates on every navigation and treats an outage as an error rather than a sign-out                                                |
| Nitro proxy, per-request query client, and request ID shared by page and API                            | **Complete** | US-AUTH-003; spec B-52                                                                                                                                                        |
| Auth gate: server cookie gate, client revalidating middleware, protected and auth layouts               | **Complete** | US-AUTH-003; spec B-12, B-45                                                                                                                                                  |
| UI kit: Button, Modal, Toast, TextField with Storybook stories and a visual-regression CI job           | **Complete** | US-AUTH-004; spec B-39, B-48                                                                                                                                                  |
| Register, log-in and dashboard password-change forms with field-level errors                            | **Complete** | US-AUTH-004; spec B-38, B-50                                                                                                                                                  |
| Password reset: `user_password_resets`, the forgot and reset endpoints, and the arq email job           | **Complete** | US-AUTH-005; spec B-14, B-15, B-36, B-47; the pages ship with it (Resend client, `with_client_telemetry`, retries); the two pages (B-36) arrive in the slice 04 frontend half |
| Idempotency keys: replay, release on failure, reuse refusal, lease takeover                             | **Complete** | US-INFRA-009; spec B-17, B-18, B-40, B-44, B-53                                                                                                                               |
| Smoke suite (`pnpm smoke`), run by CI against the compose stack built from the production images        | **Complete** | US-INFRA-010; spec B-28 as amended on 2026-09-24; `e2e/smoke/services.smoke.ts`                                                                                               |
| Railway configuration, one file per service, with the API's `alembic upgrade head` pre-deploy command   | **Complete** | US-INFRA-010; configuration only, because the template is never deployed and the first real deploy happens in the first fork                                                  |
| Accessibility: Lighthouse 100 on all seven pages, keyboard operability, and reduced motion              | **Complete** | US-INFRA-011; spec B-27, B-48; `e2e/accessibility.spec.ts`                                                                                                                    |
| Hourly cleanup job `delete_expired_rows` (sessions, idempotency keys, webhook ledger)                   | **Complete** | US-INFRA-012; spec B-26; arq cron at minute 0, batches of 1000; replaces the Express template's in-process timer and pg_cron schedule                                         |

## Billing

| Feature                                                                                                          | Status       | Notes                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------- |
| Stripe Checkout: `POST /v1/billing/checkout`, replayed by `Idempotency-Key`                                      | **Partial**  | US-BILLING-001; spec B-33, B-40; backend complete, the dashboard button arrives in the slice 06 client half |
| Billing portal: `POST /v1/billing/portal`                                                                        | **Partial**  | US-BILLING-002; spec B-22; backend complete, the dashboard button arrives in the slice 06 client half       |
| Stripe webhook: signature check, five-event allowlist, the `billing_webhook_events` ledger, `user_subscriptions` | **Complete** | US-BILLING-003; spec B-6, B-7, B-20, B-21, B-34, B-41, B-42, B-51                                           |
| stripe-mock as the `e2e` compose profile                                                                         | **Complete** | spec Architecture; `docker compose --profile e2e up`                                                        |

## Landing

| Feature                                        | Status       | Notes                                                                               |
| ---------------------------------------------- | ------------ | ----------------------------------------------------------------------------------- |
| Landing page with links to log in and register | **Complete** | US-LANDING-001; spec B-49; PR #7; the log-in and register pages shipped in slice 03 |

## Admin

| Feature                                                              | Status       | Notes                   |
| -------------------------------------------------------------------- | ------------ | ----------------------- |
| Roles, `require_admin`, `GET /v1/admin/users`, and the `/admin` page | **Complete** | US-ADMIN-001; spec B-19 |

## Observability

| Feature                                                                                                  | Status       | Notes                                                                                                     |
| -------------------------------------------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------- |
| Provider call telemetry: provider, operation, duration, outcome, request ID, and a timeout on every call | **Complete** | US-OBS-001; spec B-23; `with_client_telemetry` wraps PostHog and R2                                       |
| PostHog server events and browser pageviews, identify, and reset, keyed by user ID only                  | **Partial**  | US-OBS-002; spec B-24; the four auth events on this base; the two reset events join with the reset routes |
| Sentry on the API, the browser, and Nitro, tagged with the request ID and scrubbed of credentials        | **Complete** | US-OBS-002; spec B-30                                                                                     |
| Presigned R2 uploads under server-generated keys (`POST /v1/uploads`)                                    | **Complete** | US-OBS-003; spec B-29; no page calls it yet                                                               |

## Theme

| Feature                                                                                 | Status       | Notes                                        |
| --------------------------------------------------------------------------------------- | ------------ | -------------------------------------------- |
| Light, dark, and system theme with a toggle in both layouts, applied before first paint | **Complete** | US-THEME-001; spec B-37; `e2e/theme.spec.ts` |

## Billing

| Feature                                           | Status      | Notes                                                                                        |
| ------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------- |
| Stripe checkout and customer portal               | **Planned** | Slice 06; parity with the Express template's `/v1/billing/checkout` and `/v1/billing/portal` |
| Stripe webhook with an event ledger               | **Planned** | Slice 06; served at `/v1/billing/webhook`                                                    |
| Dashboard billing actions and the checkout banner | **Planned** | Slice 06                                                                                     |

## Observability and integrations

| Feature                                         | Status      | Notes    |
| ----------------------------------------------- | ----------- | -------- |
| PostHog analytics on the server and the web app | **Planned** | Slice 07 |
| Sentry on the server and the web app            | **Planned** | Slice 07 |
| Cloudflare R2 storage client                    | **Planned** | Slice 07 |

## Excluded from parity

Features of `template-express-next` that this template deliberately does not carry, with the reason for each.

| Feature                                | Status       | Notes                                                                                          |
| -------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------- |
| `address-copilot-review` workflow      | **Excluded** | The Copilot coding agent was dropped for cost on 2026-09-18 (spec: Decisions already made)     |
| `vercel.json`                          | **Excluded** | The Docker image on Railway is the only deploy path (R-351)                                    |
| The `posts` sample resource            | **Excluded** | Every fork deletes the sample resource, so it is not carried over                              |
| Circuit breaker service                | **Excluded** | The Express breaker is never called and no provider needs one yet (spec decision, stack audit) |
| `scripts/deploy.sh`                    | **Excluded** | Railway builds each service from its committed config file, so no deploy script is needed      |
| `dev-watch.sh` and `ensure-test-db.sh` | **Excluded** | `pnpm dev` reloads both apps, and compose provides Postgres and Redis                          |
