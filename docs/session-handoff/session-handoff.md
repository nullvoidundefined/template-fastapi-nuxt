# Session handoff: template-fastapi-nuxt

## Last commit

- `a005601` feat(errors): answer every failure in the code and error envelope (#23), on `main`. This handoff lands on `docs/session-handoff-slice02` as its own pull request, because slice 02's PR 3 had not started when the session closed.

## Production state

- Nothing is deployed. The template runs locally with `docker compose up --detach --wait --no-build` after the three images are built, and the full CI graph, now eight jobs, is green on `main`.
- Postgres and Redis publish on host ports 5433 and 6380; integration tests need `TEST_DATABASE_URL=postgresql+asyncpg://app@localhost:5433/app` and `TEST_REDIS_URL=redis://localhost:6380/0`.

## Session metrics

- Four pull requests merged: #22 (IAN-167), #24 (IAN-185), #21 (IAN-166's plan), #23 (IAN-168). 36 files changed, about 1,685 lines added since `4bc6ea7`.
- Rework: 13 review findings fixed on #21, 2 fixed and 1 answered on #22, 2 fixed on #24, and 12 fixed across four rounds on #23. Copilot reviewed unrequested on every pull request and ran 13 right to 3 wrong.
- Velocity flag: PR 2 ran 38 percent over its estimate (62 minutes against 45) at four rework rounds, while the two configuration-only pull requests came in at or under. Estimate standard-tier pull requests that touch application code nearer 60 minutes than 45; the gap is specific to code with behavior worth arguing about.

## What shipped

- **#22 (IAN-167):** root ESLint covering `e2e/`, `packages/` and the root configuration files, and a `build-images` composite action giving `docker-build` and `e2e` a GitHub Actions layer cache, with compose starting the stack `--no-build`.
- **#24 (IAN-185):** the 80 percent floor moved off the unit suite alone. Both suites emit coverage data, a `coverage` job combines them and checks the floor once. Verified in CI: `Combined 2 files`, 97 percent.
- **#21 (IAN-166):** `docs/slices/slice-02-data-and-errors.md`, the five-PR plan, plus three spec amendments: the rate limiter fails closed on the four auth paths when Redis is unreachable in production and never counts in memory there; `SERVER_RATE_LIMIT_UNAVAILABLE` joins the error-code list; and the health routes are named as the one documented exception to the `{ code, error }` invariant.
- **#23 (IAN-168):** the error registry, `AppError` and its subclasses, the five exception handlers, and the envelope typed into `@repo/api-types`. Two defects fixed that it did not introduce: `ConsoleRenderer` crashing on any `exc_info` log in development, latent since slice 01; and `packages/api-types/src/schema.ts` renamed to `schemas.ts` so the enforcement lint's declarative-module exemption applies.
- **Harness:** R-211 broadened twice and synced to the Claude, Cursor and Codex tracks. Every question, and every next step handed back to the user, now goes through option tiles rather than prose.

## Pending

- **Immediate, needs the owner:** `.claude/tdd-lock.json` is deleted in the agent-governance working tree. Another session committed it today and this session's `tdd.sh close` removed it across repositories; R-410 blocks Claude from restoring it. Run `git -C <agent-governance> checkout -- .claude/tdd-lock.json`. The cross-repository reach of `tdd.sh close` is tracked as IAN-195 on Agent Governance: the lock resolves against the harness root rather than the repository the slice belongs to, and R-410 stops the session that caused the deletion from repairing it.
- **IAN-169, PR 3, about 50 minutes:** branch `feat/slice02-alembic-users` is cut off `a005601` with the ledger recorded and no commits. Carries four corrections: Alembic as a runtime dependency with `alembic.ini` and `migrations/` copied into the image and a one-shot compose `migrate` service; `Depends(get_connection, scope="function")`; the real-outage test through `get_connection`; and moving the database classification off the global handlers in `main.py`.
- **IAN-170, PR 4, about 40 minutes:** the `CORS_ORIGIN` README row, and the note that the CSRF guard and timeout must send their envelopes as raw ASGI messages rather than raising, because middleware sits outside `ExceptionMiddleware`.
- **IAN-171, PR 5, about 55 minutes:** four carried corrections, the heaviest being that the Redis counter must be atomic (a Lua script or equivalent that increments and sets the TTL together) with a concurrency test, since every B-7 case in the plan is sequential and none could fail on a racing implementation.
- **Deferred, R-801:** the engineering-audit signal fired seven times across `apps/server` and `.github/workflows` with no audit on record. Outside the slice every time it fired.
- **Codex:** at its ChatGPT usage limit until 2026-09-21 02:26 local. Every test this session came from the `test-author` fallback and every pre-merge review from a Fable agent, both recorded per R-907 and R-517.

## Next session

- Start PR 3 on the existing `feat/slice02-alembic-users` branch. Read IAN-169 first: it carries corrections that are not in the plan document.
- Files to read first: `docs/slices/slice-02-data-and-errors.md` (PR 3 block), `apps/server/app/main.py` (the handler set and where the database classification currently lives), `apps/server/app/db/engine.py`, `apps/server/tests/conftest.py` (the `build_server_app` factory), and `.github/workflows/ci.yml` (the coverage job).
- Watch for the pattern this session repeated three times: a test that passes beside a behavior rather than pinning it. Mutate new guards and confirm the test fails before trusting it.
