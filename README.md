# template-fastapi-nuxt

A full-stack application template with a FastAPI backend, a Nuxt 4 frontend, and an arq worker. It is the Python, Vue, and Nuxt counterpart of `template-express-next` and reaches feature parity with it slice by slice: cookie sessions, CSRF protection, rate limiting, idempotency keys, password reset by email, roles with an admin page, a background worker, Docker, CI, a smoke suite, and four levels of tests are here now; Stripe billing arrives with slice 06, and PostHog, Sentry, Cloudflare R2, and the theme composable with slice 07. The section [Parity with template-express-next](#parity-with-template-express-next) lists every feature of the Express template and where each one stands.

The design lives in `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md`, and the build proceeds slice by slice under `docs/slices/`. The template itself is never deployed: CI proves the production images by running the smoke suite against the compose stack built from them, and the first real deploy happens in the first fork, from the Railway configuration described under [Deployment](#deployment).

## Layout

| Path                                                                                              | What it holds                                                                 |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `apps/server`                                                                                     | FastAPI API and arq worker (uv project; `Dockerfile` and `Dockerfile.worker`) |
| `apps/client/web`                                                                                 | Nuxt 4 app (pnpm workspace package `@repo/web`; its own `Dockerfile`)         |
| `packages/tokens`                                                                                 | Design tokens, compiled to SCSS custom properties on install                  |
| `packages/api-types`                                                                              | TypeScript types generated from `apps/server/docs/openapi.yaml`               |
| `e2e`                                                                                             | Playwright end-to-end specs, run against the compose stack                    |
| `scripts`                                                                                         | `check-contract-drift.sh` and its test                                        |
| `apps/server/railway.api.toml`, `apps/server/railway.worker.toml`, `apps/client/web/railway.toml` | Railway configuration, one file per service                                   |

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
| Worker probes | http://localhost:3002 (loopback only) |
| Postgres      | localhost:5433 (`POSTGRES_HOST_PORT`) |
| Redis         | localhost:6380 (`REDIS_HOST_PORT`)    |

Postgres and Redis publish on 5433 and 6380 so that a locally installed Postgres or Redis on the standard ports does not shadow them. The compose Postgres accepts passwordless connections on the compose network; it is for local development and CI only. The API, worker, and web containers restart when they exit, as a hosting platform would restart them; the worker exits when it loses Redis and comes back healthy once Redis returns.

For live reload, run the API and the web app on the host instead (`pnpm dev`), with the compose Postgres and Redis (`docker compose up --detach --wait postgres redis`) and these variables exported in your shell:

| Variable                  | Read by           | Value for local development                                        |
| ------------------------- | ----------------- | ------------------------------------------------------------------ |
| `DATABASE_URL`            | API, worker       | `postgresql+asyncpg://app@localhost:5433/app`                      |
| `REDIS_URL`               | API, worker       | `redis://localhost:6380/0`                                         |
| `ENVIRONMENT`             | API, worker       | `development`                                                      |
| `PORT`                    | API image         | `3001`                                                             |
| `WORKER_PORT`             | worker            | `3002`                                                             |
| `DATABASE_CA_CERT`        | API, worker       | unset locally; a CA bundle path when deployed                      |
| `CORS_ORIGIN`             | API               | unset locally; the web origin when deployed                        |
| `FORWARDED_ALLOW_IPS`     | API image         | `172.28.0.10` under compose; the private network's CIDR on Railway |
| `CLIENT_URL`              | worker            | `http://localhost:3000`, the origin reset-email links open         |
| `RESEND_API_KEY`          | worker            | unset locally, so reset emails are logged instead of sent          |
| `EMAIL_FROM`              | worker            | `Template <noreply@example.test>`; a verified sender deployed      |
| `NUXT_API_BASE_URL`       | web (server side) | `http://localhost:3001`                                            |
| `SENTRY_DSN`              | API               | unset locally; the Sentry project's DSN when deployed              |
| `POSTHOG_API_KEY`         | API               | unset locally; the PostHog project key when deployed               |
| `POSTHOG_HOST`            | API               | `https://us.i.posthog.com`                                         |
| `R2_ACCOUNT_ID`           | API               | unset locally; the Cloudflare account ID when deployed             |
| `R2_BUCKET`               | API               | unset locally; the upload bucket's name when deployed              |
| `R2_ACCESS_KEY_ID`        | API               | unset locally; an R2 API token's key ID when deployed              |
| `R2_SECRET_ACCESS_KEY`    | API               | unset locally; that token's secret when deployed                   |
| `NUXT_POSTHOG_HOST`       | web (server side) | `https://us.i.posthog.com`, where `/api/ingest` forwards           |
| `NUXT_PUBLIC_POSTHOG_KEY` | web               | unset locally; the PostHog project key when deployed               |
| `NUXT_PUBLIC_SENTRY_DSN`  | web               | unset locally; the web Sentry project's DSN when deployed          |

Deployed environments set these from the platform's secrets; no value is ever committed or baked into an image.

The API reads `REDIS_URL` from slice 02 PR 5 onward, not the worker alone: the rate limiter counts there so that every replica shares one budget. `FORWARDED_ALLOW_IPS` names the single address uvicorn will honor `X-Forwarded-For` from, which under compose is the static address the `web` service holds on the project network. It is one address rather than Docker's private range because trusting the range trusts every container on it, and the rate limiter's key is only as trustworthy as that list. On Railway the web service's private address changes on every redeploy, so a deployed fork sets the private network's CIDR instead, which is the Python track's rule; only the web service reaches the API over it, since the API has no public domain.

Three of them are mandatory in production and the API refuses to start without all three: `CORS_ORIGIN`, `REDIS_URL`, and `FORWARDED_ALLOW_IPS`. Each protects something that degrades quietly rather than failing loudly when it is missing. Without `CORS_ORIGIN` the allowed-origin list is empty and the CSRF guard loses the preflight that gives its header meaning; without `REDIS_URL` the rate limiter counts per process, so a client can rotate across instances past the auth limit; and without `FORWARDED_ALLOW_IPS` uvicorn keys every proxied request on the proxy's own address, putting the whole site in one rate-limit bucket.

The integrations are optional everywhere. Without `SENTRY_DSN` the API reports no errors, without `POSTHOG_API_KEY` it sends no analytics events, and without all four `R2_*` values `POST /v1/uploads` answers 503 `UPLOADS_STORAGE_UNCONFIGURED`; each logs one warning at startup, so a missing value is visible rather than silent. The web app follows the same rule: without `NUXT_PUBLIC_POSTHOG_KEY` the browser sends no analytics, and without `NUXT_PUBLIC_SENTRY_DSN` neither the browser nor the Nitro server reports errors. The browser reaches PostHog only through the `/api/ingest` proxy, which never forwards the session cookie, and it calls `identify` with the user's ID alone. Server analytics events carry the user's ID and never an email address, and Sentry events are stripped of cookies and the `Authorization` header before they leave the process.

## Tests

| Command                           | What it runs                                                                                                                                                                                                                                                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cd apps/server && uv run pytest` | Server unit and integration tests; integration needs `TEST_DATABASE_URL` and `TEST_REDIS_URL` (the compose URLs above) and skips without them                                                                                                                                                                         |
| `pnpm exec vitest run --coverage` | Web and tokens tests, with the web app's 60 percent coverage floor                                                                                                                                                                                                                                                    |
| `pnpm test:e2e`                   | Playwright against the running compose stack (run `pnpm exec playwright install chromium` once first), including `e2e/accessibility.spec.ts`: Lighthouse scores 100 for accessibility on all seven pages, Tab reaches every control with a visible focus, and nothing animates under `prefers-reduced-motion: reduce` |
| `pnpm smoke`                      | The smoke suite: every service's health probe and the landing page, against the compose ports by default (`SMOKE_WEB_URL`, `SMOKE_API_URL`, `SMOKE_WORKER_URL` override them)                                                                                                                                         |
| `pnpm check:contract`             | Fails when `openapi.yaml` or `@repo/api-types` no longer match the code                                                                                                                                                                                                                                               |

After changing a response schema, regenerate and commit the contract:

```bash
(cd apps/server && uv run --frozen python -m app.export_openapi)
pnpm --filter @repo/api-types generate
```

## CI

`.github/workflows/ci.yml` runs `lint`, `typecheck`, `unit`, `integration`, `openapi-drift`, `docker-build`, `e2e`, and `visual-regression` in parallel, and `coverage` after `unit` and `integration`. The `e2e` job runs the Playwright suite and then the smoke suite against the compose stack it built from the production images. The final `ci` job, the status check the merge ruleset requires, fails unless every one of them succeeded, so a skipped or cancelled job cannot let a pull request through.

## Key commands

| Command                                          | What it does                                                           |
| ------------------------------------------------ | ---------------------------------------------------------------------- |
| `pnpm dev`                                       | Runs the API and the web app on the host with live reload              |
| `docker compose up --build --detach --wait`      | Builds the three images and runs the whole stack                       |
| `pnpm build`                                     | Builds every workspace package, the web app included                   |
| `pnpm lint` and `pnpm typecheck`                 | ESLint and vue-tsc across the workspace (ruff and mypy run in the API) |
| `pnpm format` and `pnpm format:check`            | Prettier over the repository                                           |
| `cd apps/server && uv run alembic upgrade head`  | Brings a database to the latest migration                              |
| `pnpm smoke`                                     | The smoke suite against the compose stack or a deployment              |
| `pnpm test:visual` and `pnpm test:visual:update` | The Storybook visual-regression suite, and a baseline refresh          |
| `pnpm check:contract`                            | Fails when `openapi.yaml` or `@repo/api-types` drifted from the code   |

## Deployment

The template itself is never deployed (owner decision, 2026-09-24). A fork deploys it to Railway as three services built from their own Dockerfiles, beside a Postgres database (Neon, or Railway's own) and a Railway Redis. Each service reads its configuration from a committed TOML file, which names the Dockerfile, the healthcheck path Railway waits on before routing traffic to a new deploy, and the restart policy. No variable or secret is committed in any of them.

| Service  | Root Directory      | Config File                        | Healthcheck     | Notes                                                    |
| -------- | ------------------- | ---------------------------------- | --------------- | -------------------------------------------------------- |
| `api`    | `apps/server`       | `/apps/server/railway.api.toml`    | `/health/ready` | Runs `alembic upgrade head` as its pre-deploy command    |
| `worker` | `apps/server`       | `/apps/server/railway.worker.toml` | `/health/ready` | Never migrates; the API's pre-deploy command owns schema |
| `web`    | the repository root | `/apps/client/web/railway.toml`    | `/api/health`   | Builds from the root because it needs the workspace      |

Railway builds a service from its Root Directory but reads a config file only from an absolute path in the repository, which is why each service sets both. The API's pre-deploy command runs once per deploy on the new image, before any replica takes traffic, so replicas never race each other to migrate and no replica serves against an unmigrated schema.

Set these variables on each service before its first deploy. Railway variables are per service, so a value the API and the worker both need is set on both. Mark every secret as sealed.

| Variable              | Service     | Value                                                                                                    |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------------- |
| `ENVIRONMENT`         | api, worker | `production`, or `staging` for a staging environment; never left unset                                   |
| `DATABASE_URL`        | api, worker | Secret. The Postgres URL with the `postgresql+asyncpg://` scheme                                         |
| `DATABASE_CA_CERT`    | api, worker | The path of a CA bundle when the database's certificate needs one; unset otherwise                       |
| `REDIS_URL`           | api, worker | Secret. The Railway Redis URL; the API refuses to start in production without it                         |
| `CORS_ORIGIN`         | api         | The web service's public origin; the API refuses to start in production without it                       |
| `FORWARDED_ALLOW_IPS` | api         | The web service's private-network address; the API refuses to start in production without it             |
| `PORT`                | api, web    | Injected by Railway                                                                                      |
| `PORT`, `WORKER_PORT` | worker      | The same value, such as `3002`: Railway probes `PORT`, and the worker serves its probes on `WORKER_PORT` |
| `CLIENT_URL`          | worker      | The web service's public origin, from which the reset-email link is built                                |
| `RESEND_API_KEY`      | worker      | Secret. Without it, reset emails are logged rather than sent                                             |
| `EMAIL_FROM`          | worker      | A sender address on a domain verified with Resend                                                        |
| `NUXT_API_BASE_URL`   | web         | The API's private-network URL, such as `http://api.railway.internal:<port>`                              |

Billing adds the Stripe variables and the webhook endpoint (`/v1/billing/webhook`) with slice 06, and slice 07 adds the PostHog, Sentry, and R2 variables; each slice extends this table.

After the first deploy, run the smoke suite against the live URLs and poll the health endpoints until they are green, as the workspace deploy-monitoring rule requires. The worker has no public address on Railway, so its probe is left out:

```bash
SMOKE_WEB_URL=https://<web domain> SMOKE_API_URL=https://<api domain> pnpm smoke --grep-invert worker
```

## Project conventions

- Every mutating request carries `X-Requested-With: XMLHttpRequest`, the header-only CSRF guard, and the typed client adds it for you.
- The Pydantic schemas are the one source of the API contract; `@repo/api-types` is generated from `openapi.yaml`, and CI fails when either drifts.
- Tests live in their own trees: `apps/server/tests/unit` and `apps/server/tests/integration` for the API and worker, `apps/client/web/tests/nuxt` for the web app, and `e2e/` for the browser specs.
- A TypeScript module exports one thing, object keys are sorted, and two or more reads of one object are destructured; the push-time lint enforces all three.
- The design tokens in `packages/tokens` are the only source of colors, spacing, and type sizes, and a stylesheet that names a token that does not exist fails a test.

The repository's `CLAUDE.md` files and the design spec hold the full conventions.

## Parity with template-express-next

This template is checked against `template-express-next` feature by feature. Where the Express template's approach was replaced rather than copied, the notes say with what and why.

| Express feature                                                       | Here                                                                                                                                                                                    |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Register, log in, log out, read and change the signed-in user         | Complete                                                                                                                                                                                |
| Forgot and reset password with a Resend email                         | Complete; the email is sent by an arq job with retries, where Express made an unawaited call                                                                                            |
| Roles, the admin guard, and the `/admin` page                         | Complete, and beyond Express: `GET /v1/admin/users` feeds a real user list                                                                                                              |
| The seven pages and the auth route gate                               | Complete; every page scores 100 for accessibility in Lighthouse                                                                                                                         |
| API proxy on the web server                                           | Complete (the Nitro route `server/api/[...path].ts`)                                                                                                                                    |
| CSRF header guard, rate limiting, idempotency keys, security headers  | Complete; rate limits are counted atomically in Redis and shared by every replica                                                                                                       |
| Health endpoints                                                      | Complete, plus the Nuxt `/api/health` route and the worker's own probes                                                                                                                 |
| Background worker                                                     | Complete (arq in place of BullMQ, with a real email job and a heartbeat)                                                                                                                |
| OpenAPI document                                                      | Complete, generated from the code, with typed client types and a drift check                                                                                                            |
| UI kit with Storybook and visual regression                           | Complete; the billing component stories arrive with billing                                                                                                                             |
| Docker and compose                                                    | Complete: three images, and compose runs a one-shot migration before the API and worker                                                                                                 |
| CI                                                                    | Complete, with more jobs than Express and one aggregate required check                                                                                                                  |
| Smoke suite                                                           | Complete; it runs in CI against the compose stack rather than against a live deployment                                                                                                 |
| Railway configuration (`railway.toml`)                                | Complete, one file per service; the template is never deployed itself                                                                                                                   |
| Stripe checkout, portal, webhook ledger, and the billing dashboard UI | Arrives with slice 06                                                                                                                                                                   |
| PostHog analytics, Sentry, Cloudflare R2, and the theme               | Arrive with slice 07                                                                                                                                                                    |
| Hourly cleanup of expired sessions and stale idempotency keys         | Arrives as the arq cron job `delete_expired_rows`, after slice 06's billing table exists; it replaces both the in-process timer and the pg_cron schedule, so one code path does the job |
| `scripts/deploy.sh`                                                   | Not ported: Railway builds each service from its config file on push, so no script is needed                                                                                            |
| `dev-watch.sh`, `ensure-test-db.sh`, and `dev:payments`               | Not ported: `pnpm dev` reloads both apps and compose provides the databases; `stripe listen` belongs to slice 06                                                                        |
| Circuit breaker service                                               | Dropped: the Express breaker is never called and no provider needs one yet (spec decision)                                                                                              |
| `address-copilot-review` workflow                                     | Excluded: the Copilot coding agent was dropped for cost on 2026-09-18                                                                                                                   |
| `vercel.json`                                                         | Excluded: the Docker image on Railway is the only deploy path                                                                                                                           |
| The `posts` sample resource                                           | Excluded: every fork deletes the sample resource, so it is not carried over                                                                                                             |
