#!/usr/bin/env bash
# B-4 test for scripts/check-contract-drift.sh, the check CI's openapi-drift job and lefthook's
# pre-push hook run. Each case works on a throwaway copy of the repository, so the real tree is
# never touched: the copy excludes git metadata, installed dependencies, and build output, and
# symlinks the original node_modules directories and the server virtualenv so `uv run` and
# `pnpm exec` work without an install. The cases are: the script exits 0 on an unmodified copy;
# after a field is added to HealthLiveness it exits 1 and its output names both committed contract
# files; and no run writes anything into the copy's tree. Prints PASS or FAIL per case and exits
# non-zero when any case fails.

set -uo pipefail

TEST_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$TEST_DIRECTORY/../.." && pwd)"
DRIFT_SCRIPT_RELATIVE="scripts/check-contract-drift.sh"
OPENAPI_RELATIVE="apps/server/docs/openapi.yaml"
SCHEMA_TS_RELATIVE="packages/api-types/src/schema.ts"
HEALTH_SCHEMA_RELATIVE="apps/server/app/schemas/health.py"

WORK_DIRECTORY="$(mktemp -d)"
FAILED_CASE_COUNT=0

# Remove the throwaway directory however the test exits.
# Arguments: none.
remove_work_directory() {
    rm -rf "$WORK_DIRECTORY"
}
trap remove_work_directory EXIT

# Record one case outcome and print it as PASS or FAIL with its name and detail.
# Arguments: $1 outcome (0 for pass), $2 case name, $3 detail shown on failure.
report_case() {
    if [ "$1" -eq 0 ]; then
        echo "PASS: $2"
    else
        echo "FAIL: $2: $3"
        FAILED_CASE_COUNT=$((FAILED_CASE_COUNT + 1))
    fi
}

# Build a copy of the repository without git metadata, dependencies, or build output, then link
# the original installed dependencies into it.
# Arguments: $1 destination directory. Prints nothing; returns non-zero if the copy fails.
build_tree_copy() {
    local copy_root="$1"
    mkdir -p "$copy_root"
    rsync -a \
        --exclude '.git' \
        --exclude 'node_modules' \
        --exclude 'apps/server/.venv' \
        --exclude '.nuxt' \
        --exclude '.output' \
        --exclude 'dist' \
        --exclude '__pycache__' \
        --exclude '.env*' \
        "$SOURCE_ROOT/" "$copy_root/" || return 1
    link_installed_dependencies "$copy_root"
}

# Symlink every installed node_modules directory and the server virtualenv into the copy.
# Arguments: $1 copy root.
link_installed_dependencies() {
    local copy_root="$1"
    local modules_directory relative_path
    for modules_directory in \
        "$SOURCE_ROOT/node_modules" \
        "$SOURCE_ROOT"/packages/*/node_modules \
        "$SOURCE_ROOT/apps/client/web/node_modules" \
        "$SOURCE_ROOT/apps/server/.venv"; do
        [ -d "$modules_directory" ] || continue
        relative_path="${modules_directory#"$SOURCE_ROOT"/}"
        mkdir -p "$(dirname "$copy_root/$relative_path")"
        ln -s "$modules_directory" "$copy_root/$relative_path"
    done
}

# Print a sorted digest of every regular file in the copy, skipping linked dependencies and
# interpreter caches, so any file the drift script creates, edits, or deletes changes the output.
# Arguments: $1 copy root.
snapshot_tree_digest() {
    local copy_root="$1"
    (
        cd "$copy_root" || exit 1
        find . \( -name node_modules -o -name .venv -o -name __pycache__ \) -prune \
            -o -type f -print0 |
            LC_ALL=C sort -z |
            xargs -0 shasum -a 256
    )
}

# Run the copy's drift script with no arguments from outside the copy, so it must find the repo
# root from its own path. DATABASE_URL is unset because CI's drift job has no database.
# UV_NO_SYNC stops uv from rewriting the symlinked virtualenv's editable install to point at the
# copy, and PYTHONPATH makes the copy's `app` package win over that editable install.
# Arguments: $1 copy root, $2 file receiving combined stdout and stderr. Returns the exit code.
run_drift_script() {
    local copy_root="$1"
    local output_file="$2"
    (
        cd "$WORK_DIRECTORY" || exit 1
        env -u DATABASE_URL \
            UV_NO_SYNC=1 \
            PYTHONPATH="$copy_root/apps/server" \
            "$copy_root/$DRIFT_SCRIPT_RELATIVE" >"$output_file" 2>&1
    )
}

# Add a defaulted `version` field to HealthLiveness in the copy, directly under its status field.
# Arguments: $1 copy root. Returns non-zero when the class or its status field is not found.
add_field_to_health_liveness() {
    local health_schema_path="$1/$HEALTH_SCHEMA_RELATIVE"
    local edited_path="$health_schema_path.edited"
    [ -f "$health_schema_path" ] || return 1
    awk '
        /^class HealthLiveness/ { in_liveness = 1 }
        /^class / && !/^class HealthLiveness/ { in_liveness = 0 }
        { print }
        in_liveness && !inserted && /^[[:space:]]+status:/ {
            match($0, /^[[:space:]]+/)
            print substr($0, 1, RLENGTH) "version: str = \"1\""
            inserted = 1
        }
    ' "$health_schema_path" >"$edited_path" || return 1
    mv "$edited_path" "$health_schema_path"
    grep -q 'version: str = "1"' "$health_schema_path"
}

# Case 1 and case 3: an unmodified copy passes and is left byte-identical.
# Arguments: none.
test_unmodified_tree_passes() {
    local copy_root="$WORK_DIRECTORY/unmodified"
    local output_file="$WORK_DIRECTORY/unmodified.out"
    local digest_before digest_after exit_code outcome
    build_tree_copy "$copy_root" || {
        report_case 1 "setup: copy the tree" "rsync or symlinking failed"
        return
    }
    if [ ! -x "$copy_root/$DRIFT_SCRIPT_RELATIVE" ]; then
        report_case 1 "unmodified tree exits 0" \
            "$DRIFT_SCRIPT_RELATIVE is missing or not executable"
        return
    fi
    digest_before="$(snapshot_tree_digest "$copy_root")"
    run_drift_script "$copy_root" "$output_file"
    exit_code=$?
    digest_after="$(snapshot_tree_digest "$copy_root")"
    outcome=0
    [ "$exit_code" -eq 0 ] || outcome=1
    report_case "$outcome" "unmodified tree exits 0" \
        "exit $exit_code; output: $(cat "$output_file")"
    outcome=0
    [ "$digest_before" = "$digest_after" ] || outcome=1
    report_case "$outcome" "unmodified tree is left byte-identical" \
        "the script changed files in the tree"
}

# Case 2 and case 3: a schema field added without regenerating fails, names both contract files,
# and leaves the tree byte-identical.
# Arguments: none.
test_schema_change_without_regeneration_fails() {
    local copy_root="$WORK_DIRECTORY/drifted"
    local output_file="$WORK_DIRECTORY/drifted.out"
    local digest_before digest_after exit_code outcome
    build_tree_copy "$copy_root" || {
        report_case 1 "setup: copy the tree" "rsync or symlinking failed"
        return
    }
    if [ ! -x "$copy_root/$DRIFT_SCRIPT_RELATIVE" ]; then
        report_case 1 "drifted schema exits 1" "$DRIFT_SCRIPT_RELATIVE is missing or not executable"
        return
    fi
    add_field_to_health_liveness "$copy_root" || {
        report_case 1 "setup: add a field to HealthLiveness" "$HEALTH_SCHEMA_RELATIVE not editable"
        return
    }
    digest_before="$(snapshot_tree_digest "$copy_root")"
    run_drift_script "$copy_root" "$output_file"
    exit_code=$?
    digest_after="$(snapshot_tree_digest "$copy_root")"
    outcome=0
    [ "$exit_code" -eq 1 ] || outcome=1
    report_case "$outcome" "drifted schema exits 1" "exit $exit_code; output: $(cat "$output_file")"
    outcome=0
    grep -qF "$OPENAPI_RELATIVE" "$output_file" || outcome=1
    report_case "$outcome" "drift output names $OPENAPI_RELATIVE" "output: $(cat "$output_file")"
    outcome=0
    grep -qF "$SCHEMA_TS_RELATIVE" "$output_file" || outcome=1
    report_case "$outcome" "drift output names $SCHEMA_TS_RELATIVE" "output: $(cat "$output_file")"
    outcome=0
    [ "$digest_before" = "$digest_after" ] || outcome=1
    report_case "$outcome" "drifted tree is left byte-identical" \
        "the script changed files in the tree"
}

test_unmodified_tree_passes
test_schema_change_without_regeneration_fails

if [ "$FAILED_CASE_COUNT" -gt 0 ]; then
    echo "$FAILED_CASE_COUNT case(s) failed"
    exit 1
fi
echo "all cases passed"
