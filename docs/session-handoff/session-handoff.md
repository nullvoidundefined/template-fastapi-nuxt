# Session handoff: template-fastapi-nuxt

## Last commit

- `a04a82b` Slice 02 PR 5: rate limiting and the Redis settings guard (#28), on `main`. This handoff lands on `docs/slice02-complete` as its own pull request.

## Production state

- Nothing is deployed. The template runs locally with `docker compose up --detach --wait`, which now brings the schema to head through a one-shot `migrate` service before `api` or `worker` start. The full CI graph, ten checks, is green on `main`.
- Postgres and Redis publish on host ports 5433 and 6380. Integration tests need `TEST_DATABASE_URL=postgresql+asyncpg://app@localhost:5433/app` and `TEST_REDIS_URL=redis://localhost:6380/0`.
- Compose now fixes a subnet (`172.28.0.0/16`) and gives `web` the static address `172.28.0.10`, because `FORWARDED_ALLOW_IPS` on the API must name one address and uvicorn's allowlist takes addresses rather than service names.

## Session metrics

- Three pull requests merged: #26 (IAN-169), #27 (IAN-170), #28 (IAN-171). Slice 02 is complete and IAN-166 is closed.
- Test count went from 120 to 194. Estimates ran 1.6 to 1.9 times over on every ticket: 95 minutes against 50, 63 against 40, 105 against 55.
- Velocity: the estimates are not wrong about the work, they omit two things. Review rounds, and the test updates a new guard forces on an existing suite (PR 4 broke 19 passing tests, all correctly). Estimate a standard ticket touching application code at 60 minutes plus about 20 for review, and a complex one at double.
- Codex reached its usage limit during IAN-171, so its tests and its pre-merge review came from the in-house fallbacks (R-907, R-517). The test-author agent takes about 15 minutes where Codex takes 4. Any ticket starting while Codex is limited should be estimated at roughly double.

## What shipped

- **#26 (IAN-169):** Alembic, the first revision (the `set_updated_at` trigger function, `users`, the unique index on `lower(email)`), and `get_connection`, the per-request transaction at `scope="function"`. The database classification moved off the global handlers into `get_connection`, so only a route that really opened a connection can report a database outage.
- **#27 (IAN-170):** security headers, CORS, the CSRF header guard, and the 30 second timeout, in one ordered chain. `send_error_envelope` was extracted so every pure ASGI layer writes the same envelope without raising into a handler that cannot see it.
- **#28 (IAN-171):** the rate limiter. Two buckets counted in Redis by one Lua script that increments and arms the window together, keyed on the address uvicorn resolved and never on a header. Deployed environments never count in process; when Redis is gone the four auth paths fail closed and everything else is served.

## Pending

- **IAN-306, trivial:** the production TLS branch in `migrations/env.py` has no test. `build_connect_args` is covered, but the branch that decides to pass it is not, because the integration fixture always sets `sqlalchemy.url` and compose runs as development. Testing it means moving `build_migration_engine` into an importable module, since `env.py` runs the chain at import.
- **IAN-312, trivial:** integration tests fail rather than skip when `TEST_REDIS_URL` or `TEST_DATABASE_URL` names a service that is not answering. The documented verification command goes red for environmental reasons, which trains the reader to ignore red. `tests/integration/middleware/conftest.py` already does this correctly and is the model.
- **Untested change on `main`:** `EXPOSED_CORS_HEADERS` in `app/main.py`. Nothing asserts `Access-Control-Expose-Headers`. Recorded in the PR document rather than left implicit.
- **Slice 03 has no plan yet.** The spec's slice plan describes it; the five-PR breakdown does not exist. That is the next planning task, and it needs Gate 1 approval before any code.
- **Deferred, R-801:** the engineering-audit signal has now fired on `apps/server` for three sessions running with no audit on record. Slice 02 added eleven commits to that surface.

## Next session

- Plan slice 03 (auth: register, login, logout, session resolution) as its own document under `docs/slices/`, following the shape of `slice-02-data-and-errors.md`, then take Gate 1 approval before writing code.
- Read first: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md` for the slice-03 criteria, `apps/server/app/middleware/` for the chain slice 03's routes arrive behind, and `apps/server/app/db/session.py` for the dependency its repositories will take.
- Three lessons worth carrying, each of which cost time this session. A test that wraps a middleware around a bare `Response` proves nothing about what a client receives; drive the built application. A fixture naming a default port for a shared service is a latent cross-test dependency; name a closed port as the database URL already does. And a mutation check without an assertion that the mutation applied is worse than none, because it returns a confident wrong answer.
