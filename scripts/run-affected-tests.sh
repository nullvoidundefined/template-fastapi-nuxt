#!/usr/bin/env bash
# Pre-push: runs only the tests the pushed changes affect (spec: lefthook); CI runs the full suites.
#
# Changes are measured against the merge base with origin/main. Changed pytest modules run
# directly, and a changed server source file runs every test module whose name contains the
# source module's name (app/workers/health.py runs test_health.py, test_worker_health.py, and
# test_health_redis.py), so a module's tests are not missed for a naming difference.
# Vitest runs the tests related to the changed files (`--changed`). Playwright runs the specs
# affected by the changes (`--only-changed`) when the compose stack answers on WEB_BASE_URL, and
# says so and skips when it does not, because end-to-end tests need the running stack.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WEB_BASE_URL="${WEB_BASE_URL:-http://localhost:3000}"
cd "$repo_root"

base_ref="$(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD~1)"
# One path per line; bash 3.2 (macOS) has no mapfile, so the list stays a newline-separated string.
changed_files="$(git diff --name-only --diff-filter=ACMR "$base_ref" HEAD)"

# Print each pytest module affected by the changed files, relative to apps/server.
list_affected_pytest_modules() {
    local changed_file module_name
    while IFS= read -r changed_file; do
        case "$changed_file" in
            apps/server/tests/*/test_*.py | apps/server/tests/test_*.py)
                echo "${changed_file#apps/server/}"
                ;;
            apps/server/app/*.py)
                module_name="$(basename "$changed_file" .py)"
                find apps/server/tests -name "test_*${module_name}*.py" | sed 's|^apps/server/||'
                ;;
        esac
    done <<<"$changed_files" | sort -u
}

# Run the affected pytest modules, or say there are none.
run_affected_pytest() {
    local affected_modules
    affected_modules="$(list_affected_pytest_modules)"
    if [ -z "$affected_modules" ]; then
        echo "pre-push: no affected pytest modules"
        return 0
    fi
    echo "pre-push: affected pytest modules: $(echo "$affected_modules" | tr "\n" " ")"
    # shellcheck disable=SC2086 # one module path per word
    (cd apps/server && uv run --frozen pytest -q $affected_modules)
}

# Run the Vitest tests related to the changes since the base commit.
run_affected_vitest() {
    echo "pre-push: Vitest tests related to the changes"
    pnpm exec vitest run --changed "$base_ref" --passWithNoTests
}

# Run the affected Playwright specs when the compose stack is up, else say it was skipped.
run_affected_playwright() {
    if ! curl --silent --fail --max-time 2 "$WEB_BASE_URL/api/health" >/dev/null; then
        echo "pre-push: the stack is not running at $WEB_BASE_URL, so Playwright is skipped (CI runs it)"
        return 0
    fi
    echo "pre-push: Playwright specs affected by the changes"
    pnpm exec playwright test --only-changed="$base_ref" --pass-with-no-tests
}

run_affected_pytest
run_affected_vitest
run_affected_playwright
