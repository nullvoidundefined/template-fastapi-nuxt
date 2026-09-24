# template-fastapi-nuxt

A full-stack application template with a FastAPI backend, a Nuxt 4 frontend, and an arq worker. It duplicates every feature of `template-express-next` (cookie sessions, CSRF protection, rate limiting, idempotency keys, Stripe, Resend, PostHog, Cloudflare R2, Sentry, a background worker, Docker, CI, and four levels of tests) on the Python, Vue, and Nuxt convention tracks.

The design lives in `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md`, and the build proceeds slice by slice under `docs/slices/`. Slice 01, the walking skeleton, provides the three services, their health probes, the typed API contract, the containers, and CI; the features arrive in later slices.

## Layout

| Path                 | What it holds                                                                 |
| -------------------- | ----------------------------------------------------------------------------- |
| `apps/server`        | FastAPI API and arq worker (uv project; `Dockerfile` and `Dockerfile.worker`) |
| `apps/client/web`    | Nuxt 4 app (pnpm workspace package `@repo/web`; its own `Dockerfile`)         |
| `packages/tokens`    | Design tokens, compiled to SCSS custom properties on install                  |
| `packages/api-types` | TypeScript types generated from `apps/server/docs/openapi.yaml`               |
| `e2e`                | Playwright end-to-end specs, run against the compose stack                    |
| `scripts`            | `check-contract-drift.sh` and its test                                        |

## Prerequisites

- Node 22 and pnpm 10 (`corepack enable` picks up the pinned version)
- Python 3.13 and uv
- Docker with Compose v2

## Setup

```bash
pnpm install
```

This installs the workspace, builds `@repo/tokens`, and installs the lefthook git hooks: formatters and linters on staged files at commit, and the suites plus the contract check at push. Then install the server environment:

```bash
cd apps/server && uv sync
```

## Running

The whole stack, with Postgres 17 and Redis 7, returning once every container reports healthy:

```bash
docker compose up --build --detach --wait
```

| Service       | Address                               |
| ------------- | ------------------------------------- |
| Web           | http://localhost:3000                 |
| API           | http://localhost:3001                 |
| Worker probes | port 3002 inside the compose network  |
| Postgres      | localhost:5433 (`POSTGRES_HOST_PORT`) |
| Redis         | localhost:6380 (`REDIS_HOST_PORT`)    |

Postgres and Redis publish on 5433 and 6380 so that a locally installed Postgres or Redis on the standard ports does not shadow them. The compose Postgres accepts passwordless connections on the compose network; it is for local development and CI only. The API, worker, and web containers restart when they exit, as a hosting platform would restart them; the worker exits when it loses Redis and comes back healthy once Redis returns.

For live reload, run the API and the web app on the host instead (`pnpm dev`), with the compose Postgres and Redis (`docker compose up --detach --wait postgres redis`) and these variables exported in your shell:

| Variable                  | Read by           | Value for local development                                     |
| ------------------------- | ----------------- | --------------------------------------------------------------- |
| `DATABASE_URL`            | API, worker       | `postgresql+asyncpg://app@localhost:5433/app`                   |
| `REDIS_URL`               | API, worker       | `redis://localhost:6380/0`                                      |
| `ENVIRONMENT`             | API, worker       | `development`                                                   |
| `PORT`                    | API image         | `3001`                                                          |
| `WORKER_PORT`             | worker            | `3002`                                                          |
| `DATABASE_CA_CERT`        | API, worker       | unset locally; a CA bundle path when deployed                   |
| `CORS_ORIGIN`             | API               | unset locally; the web origin when deployed                     |
| `FORWARDED_ALLOW_IPS`     | API image         | `172.28.0.10` under compose; the web service's address deployed |
| `CLIENT_URL`              | worker            | `http://localhost:3000`, the origin reset-email links open      |
| `RESEND_API_KEY`          | worker            | unset locally, so reset emails are logged instead of sent       |
| `EMAIL_FROM`              | worker            | `Template <noreply@example.test>`; a verified sender deployed   |
| `NUXT_API_BASE_URL`       | web (server side) | `http://localhost:3001`                                         |
| `SENTRY_DSN`              | API               | unset locally; the Sentry project's DSN when deployed           |
| `POSTHOG_API_KEY`         | API               | unset locally; the PostHog project key when deployed            |
| `POSTHOG_HOST`            | API               | `https://us.i.posthog.com`                                      |
| `R2_ACCOUNT_ID`           | API               | unset locally; the Cloudflare account ID when deployed          |
| `R2_BUCKET`               | API               | unset locally; the upload bucket's name when deployed           |
| `R2_ACCESS_KEY_ID`        | API               | unset locally; an R2 API token's key ID when deployed           |
| `R2_SECRET_ACCESS_KEY`    | API               | unset locally; that token's secret when deployed                |
| `NUXT_POSTHOG_HOST`       | web (server side) | `https://us.i.posthog.com`, where `/api/ingest` forwards        |
| `NUXT_PUBLIC_POSTHOG_KEY` | web               | unset locally; the PostHog project key when deployed            |
| `NUXT_PUBLIC_SENTRY_DSN`  | web               | unset locally; the web Sentry project's DSN when deployed       |

Deployed environments set these from the platform's secrets; no value is ever committed or baked into an image.

The API reads `REDIS_URL` from slice 02 PR 5 onward, not the worker alone: the rate limiter counts there so that every replica shares one budget. `FORWARDED_ALLOW_IPS` names the single address uvicorn will honor `X-Forwarded-For` from, which under compose is the static address the `web` service holds on the project network. It is one address rather than Docker's private range because trusting the range trusts every container on it, and the rate limiter's key is only as trustworthy as that list.

Three of them are mandatory in production and the API refuses to start without all three: `CORS_ORIGIN`, `REDIS_URL`, and `FORWARDED_ALLOW_IPS`. Each protects something that degrades quietly rather than failing loudly when it is missing. Without `CORS_ORIGIN` the allowed-origin list is empty and the CSRF guard loses the preflight that gives its header meaning; without `REDIS_URL` the rate limiter counts per process, so a client can rotate across instances past the auth limit; and without `FORWARDED_ALLOW_IPS` uvicorn keys every proxied request on the proxy's own address, putting the whole site in one rate-limit bucket.

The integrations are optional everywhere. Without `SENTRY_DSN` the API reports no errors, without `POSTHOG_API_KEY` it sends no analytics events, and without all four `R2_*` values `POST /v1/uploads` answers 503 `UPLOADS_STORAGE_UNCONFIGURED`; each logs one warning at startup, so a missing value is visible rather than silent. The web app follows the same rule: without `NUXT_PUBLIC_POSTHOG_KEY` the browser sends no analytics, and without `NUXT_PUBLIC_SENTRY_DSN` neither the browser nor the Nitro server reports errors. The browser reaches PostHog only through the `/api/ingest` proxy, which never forwards the session cookie, and it calls `identify` with the user's ID alone. Server analytics events carry the user's ID and never an email address, and Sentry events are stripped of cookies and the `Authorization` header before they leave the process.

## Tests

| Command                           | What it runs                                                                                                                                  |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `cd apps/server && uv run pytest` | Server unit and integration tests; integration needs `TEST_DATABASE_URL` and `TEST_REDIS_URL` (the compose URLs above) and skips without them |
| `pnpm exec vitest run --coverage` | Web and tokens tests, with the web app's 60 percent coverage floor                                                                            |
| `pnpm test:e2e`                   | Playwright against the running compose stack (run `pnpm exec playwright install chromium` once first)                                         |
| `pnpm check:contract`             | Fails when `openapi.yaml` or `@repo/api-types` no longer match the code                                                                       |

After changing a response schema, regenerate and commit the contract:

```bash
(cd apps/server && uv run --frozen python -m app.export_openapi)
pnpm --filter @repo/api-types generate
```

## CI

`.github/workflows/ci.yml` runs `lint`, `typecheck`, `unit`, `integration`, `openapi-drift`, `docker-build`, and `e2e` in parallel. The final `ci` job, the status check the merge ruleset requires, fails unless every one of them succeeded, so a skipped or cancelled job cannot let a pull request through.
