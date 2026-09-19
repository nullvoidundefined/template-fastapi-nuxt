# template-fastapi-nuxt: Design

Date: 2026-09-19
Status: draft; all five design sections approved by the owner in a brainstorming session on 2026-09-19
Ticket: IAN-101 (Linear project template-fastapi-nuxt); slice tickets are opened when this spec is accepted
Workstream: 2 of 3 (convention tracks, then this template, then Voyager 2.0)

## Goal

This repository becomes a full-stack application template with a FastAPI backend, an arq worker, and a Nuxt 4 frontend, and it carries every user-facing and infrastructure feature of `template-express-next` except three the owner excluded. It exists for two reasons. Future projects that choose Python for the backend start from a baseline that already has sessions, CSRF protection, rate limits, billing, observability, and four levels of tests. And Voyager 2.0 forks it as its first slice, so the template is the foundation that project's agent graph is built on.

Every rule comes from the convention tracks that agent-governance slice 01 finished on 2026-09-18: `CLAUDE-PYTHON.md` for the server and worker, `CLAUDE-FRONTEND-VUE.md` and `CLAUDE-FRONTEND-NUXT.md` for the client, and `CLAUDE-FRONTEND.md` and `CLAUDE-STYLING.md` for what both frontends share. Where this spec and a track disagree, the track wins and the spec is corrected.

## Decisions already made

Settled with the owner, one question at a time, on 2026-09-19:

| Decision | Choice | Reason |
|---|---|---|
| Repository name | `template-fastapi-nuxt` | Mirrors `template-express-next`: backend framework, then frontend framework |
| Excluded from parity | The `address-copilot-review` workflow, `vercel.json`, the `posts` sample resource | The Copilot coding agent was dropped for cost on 2026-09-18; the Docker image on Railway is the only deploy path (R-351); every fork deletes the sample resource |
| Kept from parity | Storybook with Playwright visual regression | The Vue track lists it, and dropping it would mean amending the track |
| Shared types | Generated from OpenAPI into `packages/api-types` | Pydantic schemas stay the single source; a backend change that breaks the frontend fails the type check |
| Monorepo | pnpm workspace at the root, uv project in `apps/server` | The R-301 canonical shape; root `package.json` scripts are the one entry point, as in the Express template |
| Build order | Vertical slices | Each slice ships one feature end to end and is checked for parity feature by feature |
| Password-reset email | Sent by an arq job | The request stays fast, and the job gets retries that the Express template's unawaited call never had |

## Architecture

```
apps/server/          FastAPI app and arq worker; uv project; package `app`; layout per CLAUDE-PYTHON.md
apps/client/web/      Nuxt 4; app/ and server/ roots; layout per CLAUDE-FRONTEND-NUXT.md
packages/api-types/   TypeScript generated from apps/server/docs/openapi.yaml by openapi-typescript
packages/tokens/      design tokens compiled to SCSS custom properties (ported unchanged)
packages/constants/   client-side constants, including the browser's analytics event names
e2e/                  Playwright: auth, billing, admin, accessibility, smoke, visual-regression
```

**Deployables.** Three images, each with its own Dockerfile (R-351): the API (`Dockerfile`), the worker (`Dockerfile.worker`), and the web server (`apps/client/web/Dockerfile`, Nitro `node-server` preset). `docker-compose.yml` runs all three with Postgres 17, Redis 7, and stripe-mock for local work and for the end-to-end suite.

**Request path.** The browser talks only to the Nuxt origin. A page request is rendered by Nuxt, whose `api/apiFetch.ts` calls the backend through `useRequestFetch()` so the incoming cookie reaches FastAPI during server-side rendering. Browser calls to `/api/**` go through the Nitro catch-all `server/api/[...path].ts`, which proxies to FastAPI's `/v1/**`. PostHog traffic goes through `server/api/ingest/[...path].ts`.

**Type flow.** A Pydantic schema is the definition. FastAPI generates the OpenAPI document from the routes, `uv run python -m app.export_openapi` writes it to `apps/server/docs/openapi.yaml`, and `pnpm --filter @repo/api-types generate` turns it into TypeScript. Both files are committed, and CI regenerates them and fails on any difference, so the backend, the document, and the frontend cannot drift apart.

**Analytics registries.** Server events (the six auth events) live in `app/analytics/events.py` as a `StrEnum`; browser events live in `packages/constants`. The two sets of names never overlap, so neither side needs the other's registry (R-343).

## Inputs

HTTP requests from the browser through the Nuxt origin; Stripe webhook deliveries to `POST /webhooks/stripe`; arq jobs enqueued by the API; environment variables read once at startup by pydantic-settings on the server and by `runtimeConfig` on the client. Request bodies are the Pydantic schemas in `apps/server/app/schemas/`.

## Outputs

JSON responses in the `{ data }` envelope (with `meta` for pages) on success and the `{ code, error }` envelope on failure, with the error codes of `constants/error_codes.py`; server-rendered HTML from Nuxt; emails through Resend; analytics events through PostHog; error reports through Sentry; structured JSON logs carrying the request ID.

## Backend feature map

Paths are under `/v1` except the health endpoints and the Stripe webhook.

| Feature | Endpoint or unit | Parity notes |
|---|---|---|
| Register | `POST /auth/register` | bcrypt with 12 rounds, run in a worker thread; a SHA-256 session token; 409 `AUTH_EMAIL_ALREADY_REGISTERED` on a duplicate email |
| Log in | `POST /auth/login` | Timing equalized against a dummy hash; the same `AUTH_INVALID_CREDENTIALS` for a wrong email or a wrong password |
| Log out | `POST /auth/logout` | Always 204; deletes the session row and clears the cookie |
| Current user | `GET /auth/me` | Returns `{ user }` |
| Update profile | `PATCH /auth/me` | Verifies the current password before setting a new one; deletes the user's other sessions |
| Forgot password | `POST /auth/forgot-password` | Always 200; enqueues `send_password_reset_email`, so the response never reveals whether the email exists |
| Reset password | `POST /auth/reset-password` | Single-use token with an expiry; deletes every session of the user |
| Admin gate | `require_admin` dependency | Reads `users.role`; backs the admin page's API |
| Checkout | `POST /billing/checkout` | Creates a Stripe Checkout session; the client sends an idempotency key |
| Portal | `POST /billing/portal` | 400 `BILLING_NO_ACCOUNT` when the user has no Stripe customer |
| Webhook | `POST /webhooks/stripe` | Raw body and signature verification; an event allowlist; the `billing_webhook_events` ledger with claimed, processed, and failed states |
| Health | `GET /health`, `GET /health/ready` | Registered before every router; readiness opens its own connection so a failed connect still answers 503 |
| Middleware | Seven pure ASGI classes | Request context, security headers, CORS, rate limit (100 per 15 minutes globally, 10 per 15 minutes on auth routes), a 30-second timeout, the `X-Requested-With` CSRF guard, idempotency |
| Errors | `{ code, error }` | The Express template's codes plus `ROUTING_METHOD_NOT_ALLOWED`; five exception handlers as the Python track specifies |
| Integrations | `app/clients/` | Resend, PostHog, Cloudflare R2 (presigned uploads, with no caller yet), Sentry, Stripe, the circuit breaker, and `with_client_telemetry` |
| Worker | `app/workers/` | Jobs `send_password_reset_email` and `delete_expired_rows`; HTTP health probes on port 3002 |
| Cleanup | Alembic migration | pg_cron deletes expired sessions and stale idempotency keys hourly, and skips silently where pg_cron is unavailable, in which case the arq job does the same work |
| OpenAPI | `apps/server/docs/openapi.yaml` | Exported from the app and diffed in CI |

## Frontend feature map

| Page | Route | Layout and middleware | Parity notes |
|---|---|---|---|
| Landing | `/` | `default` | Links to log in and register |
| Log in | `/login` | `auth` | Shows the reset-success banner on `?reset=true` |
| Register | `/register` | `auth` | Field-level errors from `INPUT_VALIDATION_ERROR` |
| Forgot password | `/forgot-password` | `auth` | Shows a submitted state after the request is sent |
| Reset password | `/reset-password` | `auth` | Reads `?token=`; checks that the two passwords match before submitting |
| Dashboard | `/dashboard` | `protected`, `require-session` | Profile editing and the billing checkout and portal buttons |
| Admin | `/admin` | `protected`, `require-session`, `require-admin` | A regular user is redirected |

- **Auth gate.** The three pieces the Nuxt track specifies: the Nitro `sessionCookieGate` middleware redirects a full page load that carries no session cookie; the `require-session` route middleware calls `useSessionQuery` on every navigation; and the protected layout renders only after the session resolves.
- **Data.** One fetch wrapper per backend route in `app/api/`, typed from `packages/api-types`; every query behind a composable (`useSessionQuery`, `useCheckoutMutation`, and so on); Pinia holds only the theme and UI state, never server data.
- **UI kit.** `components/ui/` carries Button, Modal, and Toast on Reka UI, with `ToastRegion` driven by `useToast()`, styled by SCSS modules from `packages/tokens`.
- **Observability.** PostHog pageviews, identify on log in and registration, and reset on log out, all through the `/ingest` proxy; `@sentry/nuxt` with the request ID as a tag.
- **Theme.** A Pinia store persisted to `localStorage`, a `data-theme` attribute, and an inline anti-flash script in the document head.
- **Storybook.** `@storybook/vue3-vite` stories for every `components/ui/` component, snapshotted by the Playwright `visual-regression` project.

## Data model

Tables follow R-334: the aggregate root takes no prefix, and every entity inside it repeats the root.

| Express table | Template table | Columns | Why the name |
|---|---|---|---|
| `users` | `users` | `id` uuid, `email` unique, `password_hash`, `role` enum `user_role` (member, admin), `created_at`, `updated_at` | The aggregate root |
| `sessions` | `user_sessions` | `id` uuid, `user_id`, `token_hash` unique, `expires_at`, `created_at`, `last_seen_at` | Owned by a user |
| `password_resets` | `user_password_resets` | `id` uuid, `user_id`, `token_hash` unique, `expires_at`, `used_at`, `created_at` | Owned by a user |
| `subscriptions` | `user_subscriptions` | `id` uuid, `user_id` unique, `stripe_customer_id`, `stripe_subscription_id`, `status`, `current_period_end`, timestamps | One per user, owned by the user |
| `stripe_events` | `billing_webhook_events` | `id` uuid, `stripe_event_id` unique, `event_type`, `status` (claimed, processed, failed), `attempted_at`, `processed_at` | The name the Python track uses; the ledger outlives any one user |
| `idempotency_keys` | `request_idempotency_keys` | `key`, `user_id`, `status_code`, `response_body` jsonb, `created_at`; unique on `(key, user_id)` | Declared as its own root, as in Voyager 2.0 |
| `posts` | none | | Excluded by the owner |

Each table arrives in the slice that first needs it, as its own Alembic revision, and a column that only a later slice uses arrives with that slice: `users.role` is added in slice 05, not slice 02.

## Acceptance criteria

Grouped by the slice that makes each one pass. Each is one behavior and one test.

Slice 01, the walking skeleton:
- B-1: `GET /health` answers 200 without touching a dependency, and `GET /health/ready` answers 503 when Postgres is unreachable.
- B-2: Every response carries an `X-Request-Id` header, which echoes an inbound one or carries a new UUID, and every log line for that request carries the same ID.
- B-3: `docker compose up` starts the API, the worker, the web server, Postgres, and Redis, and each image's `HEALTHCHECK` passes.
- B-4: CI regenerates `openapi.yaml` and `packages/api-types` and fails when either differs from the committed copy.

Slice 02, data and errors:
- B-5: An unknown path answers 404 `ROUTING_NOT_FOUND`, a wrong method answers 405 `ROUTING_METHOD_NOT_ALLOWED`, and neither ever returns FastAPI's default `{ detail }`.
- B-6: A state-changing request without `X-Requested-With: XMLHttpRequest` answers 403 `CSRF_HEADER_MISSING`, while the health routes and the Stripe webhook are exempt.
- B-7: The eleventh auth request inside 15 minutes from one IP answers 429 `RATE_LIMIT_EXCEEDED` with `Retry-After`.
- B-8: A handler that runs longer than 30 seconds answers 408 `SERVER_REQUEST_TIMEOUT`.
- B-9: A database outage during a request answers 503 `SERVER_DATABASE_UNAVAILABLE`, and an unexpected error answers 500 with no stack trace in production.

Slice 03, auth:
- B-10: Registering stores a bcrypt hash, sets an `httpOnly`, `SameSite=Lax` session cookie with a 7-day lifetime, and stores only the SHA-256 hash of its token.
- B-11: Logging in with a wrong password and with an unknown email both answer `AUTH_INVALID_CREDENTIALS`.
- B-12: A signed-out browser that loads `/dashboard` is redirected to `/login` on the first request, and a client-side navigation to `/dashboard` with an expired session is redirected as well.
- B-13: Changing the password through `PATCH /auth/me` requires the current password and signs out every other session of the user.

Slice 04, password reset:
- B-14: `POST /auth/forgot-password` answers 200 for a known and an unknown email alike, and enqueues an email job only for the known one.
- B-15: A reset token works once, fails after it expires, and a successful reset signs out every session of the user.
- B-16: The worker's `/health/ready` answers 503 when Redis is unreachable.

Slice 05, idempotency and admin:
- B-17: A repeated `POST` with the same `Idempotency-Key` from the same user within 24 hours replays the stored status and body without running the handler again.
- B-18: A handler that fails releases its idempotency claim, so the client's retry runs again instead of answering 409.
- B-19: A member calling an admin endpoint receives 403 `AUTH_ADMIN_REQUIRED`, and a member visiting `/admin` is redirected.

Slice 06, billing:
- B-20: A webhook with a bad signature answers 400 `BILLING_WEBHOOK_INVALID_SIGNATURE` and writes nothing.
- B-21: The same Stripe event delivered twice changes `user_subscriptions` once.
- B-22: The portal request for a user with no Stripe customer answers 400 `BILLING_NO_ACCOUNT`.

Slice 07, observability and integrations:
- B-23: Every outbound provider call logs the provider, the operation, the duration, and the outcome, carries the request ID, and has an explicit timeout.
- B-24: The six auth events reach PostHog from the server, and the browser's pageview events reach it through `/ingest`.
- B-25: After five failures inside 60 seconds, the circuit breaker fails calls to that provider fast for 30 seconds.

Slice 08, cleanup and closing:
- B-26: Expired sessions and idempotency keys older than 24 hours are deleted hourly, by pg_cron where it exists and by the arq job where it does not.
- B-27: Lighthouse accessibility scores 100 on the landing, log-in, and dashboard pages.
- B-28: The smoke suite passes against the deployed Railway URLs.

## Invariants

- The database never holds a raw session token or a raw password-reset token, only their SHA-256 hashes.
- Every query on a user-owned table is scoped by `user_id`.
- Every error response uses the `{ code, error }` envelope with a code from the registry.
- `openapi.yaml` and `packages/api-types` always match the code on `main`.

## Failure modes

- Invalid input answers 400 `INPUT_VALIDATION_ERROR` with the field errors; each handler has one negative-input test for an oversized body, an injection string, and malformed encoding (R-406).
- Redis unavailable: in development and test the rate limiter falls back to in-process counters with a startup warning; production refuses to start without `REDIS_URL`; the circuit breaker fails open.
- Resend, PostHog, or Sentry unavailable or unconfigured: each client logs one warning and becomes a no-op, and the request never fails because of them.
- Stripe slow or down: the client times out after 10 seconds, the circuit breaker opens after repeated failures, and the webhook answers 500 so Stripe retries.
- A second concurrent request with the same idempotency key answers 409 until the first finishes.

## State transitions

- `billing_webhook_events.status`: claimed, then processed or failed; a failed event is claimed again when Stripe redelivers it.
- `user_subscriptions.status`: mirrors the Stripe subscription status, written only by the webhook handler.
- `user_password_resets`: unused, then used (`used_at` set) or expired; neither returns to unused.

## Testing

Four levels, each a named CI job:

| Level | Runner | What it covers |
|---|---|---|
| Unit | pytest; Vitest with `@vue/test-utils` and `@nuxt/test-utils` | Services, schemas, and middleware in isolation; composables and components; one negative-input test per handler |
| Integration | pytest against real Postgres and Redis service containers | Repositories, the session flow, idempotency replay, the webhook ledger, the rate limiter, the arq jobs; each test rolls back its transaction |
| End-to-end | Playwright against the three built images, Postgres, Redis, and stripe-mock | Register, log in, log out, reset the password, the admin redirect, the checkout redirect, keyboard navigation, reduced motion |
| Smoke | Playwright smoke config against a deployed URL | Health, one log in, one error path |

The CI workflow runs `lint`, `typecheck`, `unit`, `integration`, `e2e`, `openapi-drift`, and `docker-build`, and a final `ci` job requires all of them, so `ci` stays the single check the `protect-merge` ruleset names. Visual regression runs when a Storybook story or a ui component changes. Coverage floors are 60 percent on `apps/server/app` and 60 percent on `apps/client/web/app`. lefthook runs ruff, black, mypy, ESLint, Prettier, and vue-tsc on staged files at commit, and the full suites at push.

## Observability

A request ID bound at the edge and carried through every log line, error report, and outbound call (R-341); structlog JSON in deployed environments (R-342); analytics only through the registries (R-343); no swallowed exceptions (R-344); the two health endpoints on the API and the worker (R-345); every client call instrumented with a timeout (R-346).

## Evals

Not applicable: the template contains no agentic feature. A fork that adds one, such as Voyager 2.0, brings its own eval harness.

## Security

Cookie sessions with hashed tokens; CSRF by required header; CORS restricted to `CORS_ORIGIN` with credentials; rate limits on auth routes; admin endpoints behind `require_admin`; Stripe webhooks verified by signature; secrets only in environment variables as `SecretStr`, never logged or echoed (R-102, R-104); presigned R2 URLs with server-generated keys.

## Deployment

Three Railway services built from their Dockerfiles. The API service runs `alembic upgrade head` as a release step before taking traffic. After a deploy, the smoke suite runs against the live URLs, and the health endpoints are polled until green, as the workspace deploy-monitoring rule requires.

## Slice plan

| Slice | Delivers | Estimate |
|---|---|---|
| 01 | Walking skeleton: the uv and pnpm workspaces; the FastAPI app factory with request context and health; the Nuxt shell and landing page; the three Dockerfiles and compose file; the full CI workflow green on the skeleton; lefthook; `packages/tokens`; the OpenAPI export and `api-types` generation | 4 h |
| 02 | Data and errors: the engine and connection dependency, Alembic with `users`, the envelope and the five exception handlers, structlog, and the remaining middleware | 3 h |
| 03 | Auth: `user_sessions`, the five auth endpoints for the session, the three-part Nuxt auth gate, the log-in, register, and dashboard pages, and the ui kit with Storybook | 5 h |
| 04 | Password reset: `user_password_resets`, the arq worker and its probes, Resend, the email job, and both password pages | 3 h |
| 05 | Idempotency and admin: `request_idempotency_keys` and its middleware, `users.role`, `require_admin`, and the admin page | 2.5 h |
| 06 | Billing: `user_subscriptions`, `billing_webhook_events`, checkout, portal, and webhook, the dashboard's billing buttons, and stripe-mock in the end-to-end run | 4 h |
| 07 | Observability and integrations: PostHog on both sides, Sentry on both sides, R2, the circuit breaker, `with_client_telemetry`, and the theme store | 3 h |
| 08 | Cleanup and closing: pg_cron and the arq fallback, the smoke suite, the Lighthouse assertion, a README and features-list parity audit against `template-express-next`, and the first Railway deploy | 3 h |

The total is about 27.5 hours of agent time, which already includes the 1.2 overrun ratio that code slices ran at in agent-governance slice 01. Each slice has its own Linear ticket, blocked by the one before it; slice 08 blocks Voyager 2.0's slice 01 (IAN-80). Each slice runs under the TDD lock with its feature-list row and user story written first (R-607), and its pull request merges when CI is green and Copilot's review is addressed.

## Non-goals

- The Copilot coding-agent workflow, a Vercel deployment, and the `posts` sample resource.
- Any agentic feature, eval harness, or LLM integration beyond the placeholder Anthropic client the Python track lists.
- OAuth sign-in, multi-factor authentication, and email verification, which the Express template does not have either.
- A mobile client.

## Dependencies

- Reused: the convention tracks and the enforcement hooks on agent-governance `main`; `packages/tokens` from `template-express-next`, copied as is.
- New third-party packages, each needed because no existing module provides it (R-331): FastAPI, uvicorn, SQLAlchemy, asyncpg, Alembic, pydantic-settings, redis, arq, structlog, bcrypt, httpx, stripe, resend, posthog, boto3, sentry-sdk on the server; nuxt, @tanstack/vue-query, pinia, reka-ui, @nuxt/fonts, @sentry/nuxt, posthog-js, openapi-typescript on the client; Storybook, Playwright, Vitest, and their Vue integrations for tests.

## Domain vocabulary

- **User** - an account that can sign in - chosen over: "account" and "member", because "member" is already a value of the role enum.
- **Session** - one signed-in browser, stored as `user_sessions` - chosen over: "login" and "token", because a token is only what the cookie carries.
- **Password reset** - a single-use, expiring right to set a new password, stored as `user_password_resets` - chosen over: "reset token", which names the secret rather than the record.
- **Subscription** - a user's Stripe billing state, stored as `user_subscriptions` - chosen over: "plan", which names the product rather than the user's state.
- **Webhook event** - one Stripe delivery recorded in the idempotent ledger `billing_webhook_events` - chosen over: "stripe event", because the ledger records deliveries, not Stripe's events themselves.
- **Idempotency key** - a client-supplied key that makes a `POST` or `PUT` safe to retry, stored as `request_idempotency_keys` - chosen over: "request key", which does not say what the key guarantees.
- **Job** - one arq task run by the worker - chosen over: "task", which the ticket tracker already uses for work items.
- **Role** - a user's permission level, `member` or `admin` - chosen over: "is_admin", because a boolean cannot grow a third level.
