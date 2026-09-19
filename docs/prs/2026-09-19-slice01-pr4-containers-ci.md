# PR: Containers, compose, and CI (slice 01 PR 4)

Ticket: IAN-127 (slice IAN-123). Branch: `feat/slice01-containers-ci`. Spec: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md`, criterion B-3 and the CI and lefthook paragraphs. Plan: `docs/slices/slice-01-walking-skeleton.md`, PR 4.

## Summary

This PR makes the walking skeleton run in containers and puts the real pipeline in front of `main`. Three images (API, worker, web) run with Postgres 17 and Redis 7 under one `docker compose up --build --wait`, which returns only when every container reports healthy (B-3). The worker gains its health probes and a heartbeat job. CI replaces the baseline workflow with seven parallel jobs and a final `ci` job that fails unless all seven succeeded. lefthook runs the spec's hook set, and Playwright runs the end-to-end specs written in PRs 1 and 2 for the first time. It is the last PR of slice 01.

## What changed

- **Worker (`app/workers/`):** `settings.py` holds arq's `WorkerSettings`: the Redis connection from `REDIS_URL`, lifecycle hooks that open the engine and start the probe server as a background uvicorn task on `WORKER_PORT` (default 3002), and one cron job. `health.py` serves `/health` (liveness, touches nothing) and `/health/ready` (Postgres `SELECT 1` and Redis `PING` concurrently, each within 2 seconds, 503 naming each failed dependency). `jobs/log_worker_heartbeat.py` logs `worker_heartbeat` every five minutes with its job ID bound into the log context. `Settings` gains `redis_url` (a secret, optional so the API still starts without it) and `worker_port`.
- **Images:** `apps/server/Dockerfile` (API) and `apps/server/Dockerfile.worker`, both multi-stage with uv in the builder and the non-root `app` user; `apps/client/web/Dockerfile`, Nitro's node-server output on `node:22-alpine` as the non-root `node` user, with the dependency layer built from the lockfile before the source is copied. Each has a liveness `HEALTHCHECK`. Two `.dockerignore` files keep tests, docs, and env files out of the build contexts.
- **`docker-compose.yml`:** the three services plus Postgres 17 and Redis 7, with health-gated startup order, restart on exit, and a readiness healthcheck for the worker so `up --wait` proves both dependencies. Postgres and Redis publish on loopback ports 5433 and 6380.
- **CI (`.github/workflows/ci.yml` and `.github/actions/setup-toolchain`):** `lint` (the kept R-607 step, ruff, black, ESLint, Prettier), `typecheck` (mypy strict, vue-tsc, tsc), `unit` (pytest with the 80 percent server floor, Vitest with the new 60 percent web floor, the drift-script test), `integration` (pytest against Postgres 17 and Redis 7 service containers), `openapi-drift`, `docker-build` (B-3), and `e2e` (compose plus Playwright), then `ci`. The concurrency group and read-only permissions are kept. Dependabot now covers uv, npm, and the Docker base images.
- **lefthook (`lefthook.yml`, `scripts/run-affected-tests.sh`):** at commit, Prettier, ESLint, vue-tsc, ruff, black, mypy, the em-dash check, and the Alembic migration-defaults guard on staged files, and a commit-message check that a `fix:` commit stages a test; at push, the affected tests only (changed pytest modules, Vitest `--changed`, Playwright `--only-changed` when the stack is up), the contract check, and the builds. The root `prepare` script installs the hooks inside a git work tree.
- **Playwright:** `playwright.config.ts`, with the base URLs defaulting to the compose ports.
- **Docs:** the README's layout, setup, running, environment variables, tests, and CI sections; US-INFRA-004 and feature rows for the worker probes and the pipeline; two follow-ups on the slice plan's Later list.
- **Housekeeping:** eight files that already failed Prettier on `main` are formatted (YAML now uses two-space indentation), `.claude/` and test output are ignored by Prettier, and `apps/server/.coverage`, committed by accident in PR 1, is untracked and ignored.

## Architectural decisions

- **The compose Postgres uses `trust` authentication.** A `DATABASE_URL` with a password is a credential-shaped literal the secret scanner blocks (R-108), and a placeholder password would not connect. Passwordless auth on the compose network needs no credential in any file; the ports publish on loopback only, so nothing beyond the machine can reach them. Deployed environments set real URLs from the platform's secrets.
- **Host ports 5433 and 6380.** A locally installed Postgres or Redis on the standard ports shadowed the compose ones on `localhost` on the machine this was built on, which made integration tests hit the wrong database. The ports are overridable with `POSTGRES_HOST_PORT` and `REDIS_HOST_PORT`.
- **No `.env.example`.** The harness treats it as a protected credential file, so the README documents every variable instead.
- **A heartbeat cron job.** arq refuses to start a worker with no function or cron job, so the worker crashed at startup until it had one. A five-minute heartbeat is the smallest real job and also makes an idle worker visible in the logs. A regression test constructs an arq `Worker` from `WorkerSettings`.
- **The worker restarts when it loses Redis.** arq's polling loop exits when Redis disappears. Compose's `restart: unless-stopped` stands in for the platform restarting the process, and the worker came back healthy within seconds of Redis returning.
- **Liveness in the image, readiness in compose.** The worker image's `HEALTHCHECK` calls `/health`, so a Postgres outage never restarts a working process; compose overrides it with `/health/ready`, so `up --wait` still proves both dependencies are reachable (B-3).
- **`ci` requires every job's result to be `success`.** It runs with `if: always()` and fails on `failure`, `cancelled`, or `skipped`, so a job skipped by a condition or cancelled by concurrency cannot let a pull request through the ruleset.

## Testing

- **Who wrote the tests:** the test-author agent, as the recorded fallback for Codex, which was at its usage limit (owner rule, 2026-09-19).
- **Worker slice:** `tdd.sh red` locked 15 tests across four files (liveness, readiness with fakes for each failure, a hanging dependency past the deadline, the settings fields, `WorkerSettings`, the probe server's start and release of its port, and readiness against a real unreachable and a real reachable Redis), and they went GREEN. Getting there needed two test corrections from the author: a settings test that failed with an `AttributeError`, which `tdd.sh` does not classify, and a real-Redis test that skipped until compose's Redis was up.
- **The startup crash:** the worker exited in its container because arq requires a job. A regression test that builds a real arq `Worker` failed first, then passed with the heartbeat; the RED is recorded in the fix commit.
- **Review fixes:** two tests failed first (arq's plain-text handler still attached after `configure_logging`; no `job_id` on the heartbeat's log line) and pass after; three guard tests were each shown to fail against a mutation (a silent `RedisSettings()` default, a dropped `dispose()`, a loopback bind).
- **Totals:** 79 pytest tests pass with Postgres and Redis available (97 percent coverage against the 80 percent floor), 52 Vitest tests pass (96.6 percent web coverage against the 60 percent floor), the 24-case drift test passes, and all 8 Playwright specs pass against the compose stack.
- **B-3:** `docker compose up --build --detach --wait` reports all five containers healthy, locally and in the `docker-build` job. The first CI run of this workflow passed all seven jobs and `ci`.
- **Manual probes:** the three app containers run as non-root users; the worker's readiness answered 200 with both dependencies up; with Redis stopped the worker exited and restarted, and it was healthy again once Redis returned; a source edit reuses the web image's dependency layer.

## Codex review

**Reviewer:** a separate agent on Claude Fable, standing in for Codex, which was at its ChatGPT usage limit until 2026-09-21 (owner rule, 2026-09-19). It ran every suite, actionlint, Playwright against the stack, a SIGTERM probe of the worker, seven mutation probes of the worker tests, and inspected the running containers. It reported 18 findings and no HIGH.

| #   | Severity | Finding                                                                                        | Disposition                                                                                        |
| --- | -------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | MEDIUM   | Trust-auth Postgres and auth-less Redis published on every host interface                      | Fixed: loopback-only ports                                                                         |
| 2   | MEDIUM   | arq's log lines bypassed structlog and printed twice                                           | Fixed test-first: `arq` joins the routed loggers                                                   |
| 3   | MEDIUM   | The worker's `HEALTHCHECK` used readiness, so a Postgres outage would restart a working worker | Fixed: the image checks `/health`; compose waits on `/health/ready`                                |
| 4   | MEDIUM   | The `REDIS_URL` guard was untested                                                             | Fixed: a guard test, shown to fail against a silent default                                        |
| 5   | MEDIUM   | Engine disposal on shutdown was untested                                                       | Fixed: the lifecycle test asserts disposal through SQLAlchemy's `engine_disposed` event            |
| 6   | MEDIUM   | The heartbeat took a plain dict and logged no job ID (R-341)                                   | Fixed test-first: `WorkerContext` gains `job_id`, bound for the job's duration                     |
| 7   | MEDIUM   | lefthook diverged from the spec's hook set                                                     | Fixed: the spec's commit, commit-message, and affected-tests push hooks                            |
| 8   | MEDIUM   | No PR document                                                                                 | Fixed: this document                                                                               |
| 9   | LOW      | Source edits invalidated the web image's dependency layer                                      | Fixed: `pnpm fetch` from the lockfile before the source; verified cached                           |
| 10  | LOW      | Bind address, logging setup, and concurrent readiness untested; a duplicate test               | Bind address guarded and the duplicate deleted; the other two are recorded as known gaps           |
| 11  | LOW      | `redis` imported but only transitively installed                                               | Fixed: declared directly                                                                           |
| 12  | LOW      | Healthcheck access-log noise                                                                   | Fixed for the worker's probe server; the API's access log is left for the logging work in slice 02 |
| 13  | LOW      | Build context included tests and tool state; `node:22-slim` against the track's alpine         | Fixed: tighter `.dockerignore`, `node:22-alpine`                                                   |
| 14  | LOW      | A CI comment named the wrong config file                                                       | Fixed                                                                                              |
| 15  | LOW      | `FORWARDED_ALLOW_IPS` trusts the whole Docker private range                                    | Noted in compose; revisited when the rate limiter lands                                            |
| 16  | LOW      | No Docker build cache in CI; Dependabot missed uv, npm, and Docker                             | Dependabot fixed; the build cache is on the slice plan's Later list                                |
| 17  | LOW      | ESLint does not cover `e2e/` or `packages/`                                                    | On the slice plan's Later list for slice 02                                                        |
| 18  | LOW      | Worker probes had no user story                                                                | Fixed: US-INFRA-004                                                                                |

## Reflection

The branch was cut at 19:44 local, the first CI run passed at about 20:00, and the review fixes landed by 22:00. The first surprise was that the worker could not start at all: every unit test passed because none of them built an arq `Worker`, and only running the container showed arq's rule that a worker needs a job. The second was environmental: a locally installed Postgres answered on `localhost:5432` ahead of the compose one, so the integration test failed with `role "app" does not exist` before any code was wrong. Both taught the same thing: for infrastructure, the container and the real services are the test, and this PR is where the skeleton's specs first ran against them.
