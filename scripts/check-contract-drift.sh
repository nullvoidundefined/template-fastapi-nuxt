#!/usr/bin/env bash
# Fails when the committed API contract no longer matches the code (spec B-4).
#
# Exports a fresh OpenAPI document from the FastAPI app and regenerates the TypeScript types from
# it, both into a temporary directory, then compares them with the committed
# apps/server/docs/openapi.yaml and packages/api-types/src/schema.ts. Prints a unified diff that
# names each differing committed file and exits 1 on any difference, 0 when both match, and 2 when
# a required tool is missing, so a broken runner is never mistaken for drift. It never writes into
# the working tree: `uv run --frozen` neither re-locks nor syncs. CI's openapi-drift job and the
# lefthook pre-push hook run it.
#
# To fix a reported drift, regenerate and commit both files:
#   (cd apps/server && uv run python -m app.export_openapi)
#   pnpm --filter @repo/api-types generate
set -euo pipefail

readonly COMMITTED_DOCUMENT='apps/server/docs/openapi.yaml'
readonly COMMITTED_TYPES='packages/api-types/src/schema.ts'

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

readonly OPENAPI_TYPESCRIPT="$repo_root/packages/api-types/node_modules/.bin/openapi-typescript"

# Exit 2 with an install hint when uv or openapi-typescript is unavailable.
require_tools() {
    if ! command -v uv >/dev/null 2>&1; then
        echo "check-contract-drift: uv is not installed (https://docs.astral.sh/uv/)" >&2
        exit 2
    fi
    if [ ! -x "$OPENAPI_TYPESCRIPT" ]; then
        echo "check-contract-drift: openapi-typescript is missing; run pnpm install" >&2
        exit 2
    fi
}

# Export the OpenAPI document from the app into the work directory, without bytecode files.
export_fresh_document() {
    (cd "$repo_root/apps/server" &&
        PYTHONDONTWRITEBYTECODE=1 uv run --frozen --quiet python -m app.export_openapi \
            --output "$work_dir/openapi.yaml")
}

# Generate the TypeScript types from the freshly exported document into the work directory.
generate_fresh_types() {
    (cd "$repo_root/packages/api-types" &&
        "$OPENAPI_TYPESCRIPT" "$work_dir/openapi.yaml" \
            --output "$work_dir/schema.ts" >/dev/null)
}

# Print a unified diff and return 1 when the committed file differs from its fresh copy.
compare_with_committed() {
    local committed_path="$1" fresh_path="$2"
    if diff -u --label "$committed_path (committed)" --label "$committed_path (regenerated)" \
        "$repo_root/$committed_path" "$fresh_path"; then
        return 0
    fi
    echo "contract drift: $committed_path does not match the code" >&2
    return 1
}

# Regenerate both files, compare each, and report every drifted file before failing.
main() {
    require_tools
    export_fresh_document
    generate_fresh_types
    local drift_status=0
    compare_with_committed "$COMMITTED_DOCUMENT" "$work_dir/openapi.yaml" || drift_status=1
    compare_with_committed "$COMMITTED_TYPES" "$work_dir/schema.ts" || drift_status=1
    if [ "$drift_status" -eq 0 ]; then
        echo "contract in sync: $COMMITTED_DOCUMENT and $COMMITTED_TYPES match the code"
    fi
    return "$drift_status"
}

main "$@"
