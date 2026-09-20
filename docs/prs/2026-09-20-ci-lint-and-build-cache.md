# CI hardening: root lint coverage and a Docker build cache

Ticket: IAN-167 (slice IAN-166)
Date: 2026-09-20

## Summary

This pull request closes the two items the slice-01 Later list deferred to slice 02. It adds a root ESLint configuration so that the Playwright specs, the `packages/` workspaces, and the repository's own configuration files are linted in CI and at commit, and it replaces the uncached `docker compose up --build` in the `docker-build` and `e2e` jobs with a cached buildx build. It changes no application behavior.

It lands first in the slice because the build cache shortens the two slowest jobs in the graph on each of the four pull requests behind it, so the time it costs is returned inside the same slice.

## What changed

The root `eslint.config.mjs` covers `e2e/`, `packages/`, and the root configuration files with the untyped `typescript-eslint` recommended set plus three rules the conventions require: `no-console`, `no-empty` with `allowEmptyCatch` off (R-344), and unused variables as errors with an underscore escape. `apps/` is ignored because `apps/client/web` has its own Nuxt-generated configuration and `apps/server` is Python. The generated `packages/api-types/src/schema.ts` is ignored, since it is written by openapi-typescript and its contents are not this repository's to fix.

The root `lint` script now runs `eslint .` before the per-package scripts, so CI's existing `pnpm lint` step picks the new coverage up with no change to the workflow's lint job. A `eslint-root` command in lefthook lints the same paths at commit, excluding `apps/` so that a web file is linted once, under the Nuxt rules, rather than twice under two rule sets.

For the cache, a composite action at `.github/actions/build-images` sets up buildx and builds the three images with `cache-from`/`cache-to` on the GitHub Actions cache, loading them into the runner's Docker daemon. The three compose services gained an explicit `image:` name, which is the name compose derives anyway, so the workflow can then start the stack with `docker compose up --no-build`. Local `docker compose up --build` is unchanged.

## Architectural decisions

**A composite action rather than the steps twice in the workflow.** Chosen because `docker-build` and `e2e` need the same three images, and the repository already factors shared job setup this way in `.github/actions/setup-toolchain`. The alternative, duplicating about forty lines in both jobs, would let the two copies drift, which is how a cache silently stops being shared.

**Cache scope per image, not per job.** This departs from the approved plan, which said the scope would be per job so the two jobs would not evict each other's entries. The two jobs build byte-identical images from the same commit, so a per-job scope stores two copies of the same layers and neither job can read what the other wrote on a previous run. One scope per image means whichever job runs second reads the entries the previous run wrote, and the repository's ten gigabyte cache budget is not spent twice. The plan's execution record carries this change.

**Untyped lint rules rather than type-aware ones.** Chosen because the eleven files covered here span three tsconfigs, and wiring a project service per workspace to gain type-aware rules would be a larger change than the lint gap it closes. The alternative is available later if a type-aware rule is ever the thing that would have caught a real defect.

## Testing

No unit test. The change is configuration that only CI and the commit hooks execute, and a test asserting that a YAML file contains a particular key asserts the file, not the behavior.

The behavior was verified directly instead. The root configuration lints exactly the eleven intended files, confirmed by reading `eslint . --format json` rather than trusting a zero exit code, which a configuration matching nothing also returns. A deliberate unused variable added to `e2e/health.spec.ts` was reported as an error and the file was reverted, so the configuration is known to fail on a real violation rather than only to load. `pnpm lint` passes across the root and the web package. The three images were built and the stack started with `docker compose up --no-build`, proving that the explicit image names in compose match the tags the composite action loads, which is the one way this change could break the two jobs it touches.

CI proves the remaining half: that the cache is populated on the first run and read on the second.

## Reflection

Time since implementation: written immediately after the change, about forty minutes after the slice plan it implements was approved.

What I understand now that I did not at the start: `docker compose up --build` and a buildx layer cache do not compose. Compose drives its own build, and getting the GitHub Actions cache underneath it means either teaching compose to use a container-driver builder through bake, or taking the build away from compose and handing it three already-built images. The second is less clever and easier to read six months from now, which is why the compose services now carry the image names they already had implicitly.

What I got wrong first: I ran `git checkout main` to branch from it and did not check that it failed. `main` is checked out in the primary worktree, so the checkout was refused, the branch was cut from the plan branch instead, and this pull request briefly contained the slice plan's two commits. Resetting onto `origin/main` fixed it before anything was pushed. The lesson is the one the repository's own conventions already state about verifying a merge landed rather than trusting the badge: check the result of a state-changing git command instead of the exit code of the line after it.
