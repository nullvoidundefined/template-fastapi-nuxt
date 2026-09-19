# Slice 01: Walking Skeleton

Spec: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md` (acceptance criteria B-1 to B-4)
Status: Gate 1 approved by the owner on 2026-09-19; building starts when spec PR #5 merges
Tracker: Linear project template-fastapi-nuxt; slice ticket IAN-123, with one child ticket per PR
Estimate: 4.5 hours of agent time across the four PRs

## Purpose

This slice builds nothing a user can see beyond a landing page, and that is the point. It proves every moving part of the template can be built, tested, containerized, and checked in CI before any feature depends on them: a FastAPI app that answers its health checks, a Nuxt app that renders a page, the generated type contract between them, three container images that start together, and a CI workflow whose jobs all pass. Every later slice then adds a feature to a pipeline that already works, rather than debugging the pipeline and the feature at once.

## How every PR in this slice is built

- **Tests are written by Codex**, OpenAI's coding agent run through its command-line interface, from the acceptance criteria and the PR's description, before any implementation exists (R-907, owner decision 2026-09-19). Claude's `test-author` subagent writes a test only when Codex is unavailable or rate-limited, and the PR records that.
- **Implementation follows the red, green, refactor cycle** under the harness's slice lock (R-412).
- **Before merge**, Codex reviews the PR's diff against the spec, alongside Copilot's review. Every finding is fixed or answered with a reason, and the PR body carries a "Codex review" section.
- **Gate 2:** the owner reviews and merges each PR on GitHub.

## Execution record

| PR  | Concern                         | PR number | Merged | Scope change                                                                                                                                                                            |
| --- | ------------------------------- | --------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Backend skeleton                | IAN-124   |        | Tests by the test-author agent (Codex out of quota); pre-merge review by a Fable agent found ten issues, including a password leak in the readiness log, all fixed before the PR opened |
| 2   | Frontend skeleton and workspace |           |        |                                                                                                                                                                                         |
| 3   | Type contract pipeline          |           |        |                                                                                                                                                                                         |
| 4   | Containers, compose, and CI     |           |        |                                                                                                                                                                                         |

## PRs

### PR 1: Backend skeleton

**Context:** The repository holds only the repo-setup baseline and the spec. There is no Python code, and CI's Python steps are skipped because no `pyproject.toml` exists.

**Problem:** Every backend feature depends on the app factory, the request-ID context, the logger, and the health endpoints. B-1 and B-2 cannot pass until they exist, and the Python track (`CLAUDE-PYTHON.md`) fixes their shape, so they land first and alone.

**Approach:** Create `apps/server` as a uv project (uv is the Python package and environment manager the track mandates) with the package `app`. Add `create_app()` with a lifespan that opens one async SQLAlchemy engine and disposes it on shutdown, request IDs through asgi-correlation-id (a maintained pure-ASGI package, chosen in the spec's stack audit) with a validator for `^[A-Za-z0-9._-]{1,64}$`, the request-context middleware that rejects bodies over 100 KB, structlog configuration, and the health router with `/health` and `/health/ready`.

Readiness opens its own connection, so a Postgres outage answers 503 rather than an unhandled error. Only the engine arrives here; tables, Alembic, and the error envelope belong to slice 02.

ruff, black, and mypy in strict mode are configured in `pyproject.toml`, and pytest with pytest-asyncio runs the unit suite. Removing the `hashFiles('pyproject.toml')` conditions from CI is PR 4's job, so this PR's tests run locally and in the pre-push hook.

**Contents:** `apps/server/pyproject.toml`, `uv.lock`, `.python-version`, `app/main.py`, `app/core/settings.py`, `app/core/logging.py`, `app/db/engine.py`, `app/middleware/request_context.py` (the body-size limit), `app/routers/health.py`, and tests under `apps/server/tests/`. Because `app/routers/health.py` is a new route, the R-607 checklist that CI runs requires this PR to add the feature-list row (Infrastructure: health endpoints), a user story for the health checks in `docs/user-stories/infrastructure.md`, and `e2e/health.spec.ts`.

**Tests:** B-1: `/health` answers 200 with Postgres unreachable, and `/health/ready` answers 503 when the engine cannot connect and 200 when it can (the latter against a real Postgres). B-2: a valid inbound `X-Request-Id` is echoed, an invalid or missing one is replaced by a new UUID, and a log line emitted during the request carries the same ID. The e2e spec `e2e/health.spec.ts` checks both health endpoints through the running API, satisfying the R-607 checklist.

**Review focus:** Request-ID handling: that asgi-correlation-id's ID is bound into structlog's context per request and cleared afterwards, so one request's ID can never leak into the next under concurrency, and that an inbound ID failing the validator is replaced rather than echoed.

**Size:** About 14 files and 450 lines.

### PR 2: Frontend skeleton and workspace

**Context:** PR 1 has landed; the backend runs locally. There is no Node workspace yet.

**Problem:** The Nuxt app, the pnpm workspace that holds it, and the design tokens are the base of every page in slices 03 to 07. They are independent of the backend, so they land as their own reviewable unit.

**Approach:** Add the root `package.json` and `pnpm-workspace.yaml` (pnpm is the Node package manager the R-301 layout uses), with root scripts that start both apps: `pnpm dev` runs uvicorn through uv beside `nuxt dev`. Create `apps/client/web` as a Nuxt 4 app (the Vue server-rendering framework the Nuxt track specifies) with the `default` layout, the landing page, and the Nitro route `server/api/health.get.ts` for the container health check.

Port `packages/tokens` from `template-express-next`, since tokens are framework-free and the styling track consumes them as SCSS custom properties. Scope change during the build: the generator was extended to emit every token group rather than only colors and transitions, and the accent was darkened to `#bf4f10` (hover `#a8440c`) so white text on it meets WCAG AA; see the PR 2 document. Configure ESLint with the Vue plugin, Prettier, vue-tsc, and Vitest with `@nuxt/test-utils`.

**Contents:** Root `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `apps/client/web/` (`nuxt.config.ts`, `app/app.vue`, `app/layouts/default.vue`, `app/pages/index.vue`, `app/assets/css/main.scss`, `server/api/health.get.ts`, lint and test configuration), `packages/tokens/`, and their tests, plus the R-607 artifacts for the new page and the Nitro route: the landing page and web health rows in `docs/feature-list/features.md`, the landing story in `docs/user-stories/landing.md`, and `e2e/landing.spec.ts` (B-49).

**Tests:** A component test that the landing page renders its heading and the log-in and register links with accessible names; a Nitro test that `/api/health` answers 200 without contacting the backend; a token build test that the generated SCSS contains every token the source defines; and `e2e/landing.spec.ts`, which follows both landing links to their routes (B-49).

**Review focus:** `nuxt.config.ts`: that `runtimeConfig` declares every variable with an empty default and reads values only at run time, so one image serves every environment (the Nuxt track's Environment Variables section).

**Size:** About 25 files and 600 lines, most of them configuration and the copied token package.

### PR 3: Type contract pipeline

**Context:** PRs 1 and 2 have landed. Both apps exist, but nothing connects the backend's schemas to the frontend's types.

**Problem:** The spec's type flow (Pydantic schema to OpenAPI document to generated TypeScript) must exist before the first real endpoint in slice 02, or the first endpoints would be typed by hand and the pipeline added later around them. B-4 requires that CI catches any drift between the three.

**Approach:** Add `app/export_openapi.py`, which builds the app and writes `apps/server/docs/openapi.yaml`. Add `packages/api-types` with a `generate` script that runs openapi-typescript (a generator that turns an OpenAPI document into TypeScript types) over that file into `src/schema.ts`. Commit both generated files. In the Nuxt app, `app/api/apiClient.ts` exports `createApiClient()`, which builds an openapi-fetch client (a small typed fetch wrapper that reads the same generated types, chosen in the spec's stack audit), `app/composables/useApiClient.ts` memoizes one client per Nuxt app instance, and `shared/services/resolveClientAddress.ts` returns the edge-appended last `X-Forwarded-For` entry for the server-side client now and for slice 03's Nitro proxy later, so every later route call is typed with no per-route typing by hand. The base URLs, the base headers, and the server-side cookie, request-ID, and `X-Forwarded-For` handling follow the spec's Request path paragraph; `useRequestFetch()` is not its fetch function, because openapi-fetch needs a standard `fetch` that returns a `Response`.

A script `scripts/check-contract-drift.sh` regenerates both and fails with a readable diff when either differs from the committed copy. PR 4 runs it as CI's `openapi-drift` job, and lefthook runs it at push.

**Contents:** `apps/server/app/export_openapi.py`, `apps/server/docs/openapi.yaml`, `packages/api-types/` (package manifest, generate script, generated `src/schema.ts`), `apps/client/web/app/api/apiClient.ts`, `apps/client/web/app/composables/useApiClient.ts`, `apps/client/web/shared/services/resolveClientAddress.ts`, `scripts/check-contract-drift.sh`, and tests.

**Tests:** B-4: a test adds a field to a response schema in a temporary copy of the tree and asserts the drift script fails and names the changed path; the same script passes on the unmodified tree. A unit test asserts the exported document lists `/health` and `/health/ready`, and a type test fails to compile when the client calls a path the document does not define.

**Review focus:** That the export is deterministic (sorted keys, no timestamps), because a nondeterministic export makes the drift check fail on unchanged code.

**Size:** About 8 files and 250 lines, excluding generated output.

### PR 4: Containers, compose, and CI

**Context:** PRs 1 to 3 have landed. The apps build and test locally, but nothing runs in containers, and CI still runs only the product-docs step.

**Problem:** R-351 requires every deployable artifact to ship its Dockerfile from its first commit, and every later slice's end-to-end tests need the three images running together. The CI workflow must also become the real pipeline the spec describes before features start merging through it.

**Approach:** Add the API `Dockerfile` (multi-stage, uv in the builder, non-root `app` user, `HEALTHCHECK` on `/health`); `Dockerfile.worker`, which runs an arq worker with no jobs yet (arq is the Redis-backed job queue the Python track mandates) and serves its health probes on port 3002; and `apps/client/web/Dockerfile` with the Nitro `node-server` preset. `docker-compose.yml` runs the three with Postgres 17 and Redis 7.

The worker's probe server arrives here because B-3 needs a healthy worker container. Its first real job arrives in slice 04.

Replace the baseline CI workflow with the spec's jobs: `lint`, `typecheck`, `unit`, `integration`, `e2e`, `openapi-drift`, and `docker-build`, plus the aggregate `ci` job that the `protect-merge` ruleset requires. The `e2e` job builds the images, starts compose, and runs one Playwright test (Playwright is the browser test runner) against the landing page. lefthook runs the formatters and linters on staged files at commit and the suites at push.

**Contents:** `Dockerfile`, `Dockerfile.worker`, `apps/client/web/Dockerfile`, three `.dockerignore` files, `docker-compose.yml`, `apps/server/app/workers/settings.py` and its probe server, `.github/workflows/ci.yml`, `lefthook.yml`, `playwright.config.ts`, `e2e/landing.spec.ts`, and the README's setup section.

**Tests:** B-3: the `docker-build` job builds all three images and starts compose, waits for every `HEALTHCHECK` to report healthy, and fails if any does not within a timeout. The landing-page end-to-end test asserts the heading text and that the log-in link navigates to `/login` (which answers 404 until slice 03, and the test asserts only the navigation). The worker probe has a unit test for 200 and an integration test for 503 when Redis is down.

**Review focus:** The CI workflow's job graph: that `ci` fails whenever any job fails or is skipped unexpectedly, because a skipped job that reports success would let a broken PR through the ruleset.

**Size:** About 15 files and 500 lines.

## Later list

- **Slice 03, Nitro request ID:** Nitro middleware that mints an `X-Request-Id` when the page request has none and echoes it on the page response, so every server-side API call is correlated with its page (R-341). Until then, `useApiClient()` forwards the page request's ID only when one arrived, and FastAPI mints its own otherwise. Raised by the PR 3 pre-merge review.
