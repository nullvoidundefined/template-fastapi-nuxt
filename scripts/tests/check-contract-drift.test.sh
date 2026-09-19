#!/usr/bin/env bash
# B-4 test for scripts/check-contract-drift.sh, the check CI's openapi-drift job and lefthook's
# pre-push hook run. Each case works on a throwaway copy of the repository, so the real tree is
# never touched: the copy excludes git metadata, installed dependencies, and build output, and
# symlinks the original node_modules directories and the server virtualenv so `uv run` and
# `pnpm exec` work without an install. The cases are: the script exits 0 on an unmodified copy;
# after a field is added to HealthLiveness it exits 1, its output names both committed contract
# files, and its diff shows the added field; after that same change, regenerating both committed
# files makes it exit 0 again; a hand edit to only the committed types, or to only the committed
# OpenAPI document, exits 1 and names that file alone; an unmodified copy still exits 0 with
# APP_NAME set, so the document does not depend on the environment; and no run writes anything
# into the copy's tree. Prints PASS or FAIL per case and exits non-zero when any case fails.

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

# Build a fresh copy for one case and confirm its drift script is executable, reporting a setup
# failure under the case name otherwise.
# Arguments: $1 copy root, $2 case name. Returns non-zero when the case cannot run.
prepare_case_copy() {
    local copy_root="$1"
    local case_name="$2"
    build_tree_copy "$copy_root" || {
        report_case 1 "setup: copy the tree for $case_name" "rsync or symlinking failed"
        return 1
    }
    [ -x "$copy_root/$DRIFT_SCRIPT_RELATIVE" ] || {
        report_case 1 "$case_name" "$DRIFT_SCRIPT_RELATIVE is missing or not executable"
        return 1
    }
}

# Delete the first non-blank line after line 5 of a file, so the edit lands in content rather
# than a generated header, and confirm the file changed.
# Arguments: $1 file path. Returns non-zero when the file is missing or unchanged.
delete_one_content_line() {
    local target_path="$1"
    local edited_path="$target_path.edited"
    [ -f "$target_path" ] || return 1
    awk 'NR > 5 && !deleted && NF > 0 { deleted = 1; next } { print }' \
        "$target_path" >"$edited_path" || return 1
    if cmp -s "$target_path" "$edited_path"; then
        rm -f "$edited_path"
        return 1
    fi
    mv "$edited_path" "$target_path"
}

# Change the value of the OpenAPI document's info title line in the copy's committed YAML.
# Arguments: $1 copy root. Returns non-zero when no top-level-info title line is found.
change_committed_document_title() {
    local document_path="$1/$OPENAPI_RELATIVE"
    local edited_path="$document_path.edited"
    [ -f "$document_path" ] || return 1
    awk '
        /^info:/ { in_info = 1; print; next }
        /^[^[:space:]]/ { in_info = 0 }
        in_info && !changed && /^[[:space:]]+title:/ {
            match($0, /^[[:space:]]+/)
            print substr($0, 1, RLENGTH) "title: hand-edited-title"
            changed = 1
            next
        }
        { print }
    ' "$document_path" >"$edited_path" || return 1
    mv "$edited_path" "$document_path"
    grep -q 'title: hand-edited-title' "$document_path"
}

# Regenerate both committed contract files in the copy the way a developer fixes a drift, with
# the same uv environment run_drift_script uses.
# Arguments: $1 copy root. Returns non-zero when either generator fails.
regenerate_committed_contract() {
    local copy_root="$1"
    (
        cd "$copy_root/apps/server" || exit 1
        env -u DATABASE_URL \
            UV_NO_SYNC=1 \
            PYTHONPATH="$copy_root/apps/server" \
            PYTHONDONTWRITEBYTECODE=1 \
            uv run --frozen python -m app.export_openapi
    ) || return 1
    (
        cd "$copy_root/packages/api-types" || exit 1
        ./node_modules/.bin/openapi-typescript ../../apps/server/docs/openapi.yaml \
            --output src/schema.ts >/dev/null
    )
}

# Report whether the output file names the expected path and does not name the other one.
# Arguments: $1 output file, $2 path that must appear, $3 path that must not appear, $4 case name.
report_names_only() {
    local output_file="$1"
    local expected_path="$2"
    local unexpected_path="$3"
    local case_name="$4"
    local outcome=0
    grep -qF "$expected_path" "$output_file" || outcome=1
    report_case "$outcome" "$case_name names $expected_path" "output: $(cat "$output_file")"
    outcome=0
    if grep -qF "$unexpected_path" "$output_file"; then outcome=1; fi
    report_case "$outcome" "$case_name does not name $unexpected_path" \
        "output: $(cat "$output_file")"
}

# A hand edit to only the committed TypeScript types fails and names schema.ts alone.
# Arguments: none.
test_types_only_edit_names_types_alone() {
    local copy_root="$WORK_DIRECTORY/types-edited"
    local output_file="$WORK_DIRECTORY/types-edited.out"
    local case_name="types-only edit"
    local exit_code outcome
    prepare_case_copy "$copy_root" "$case_name" || return
    delete_one_content_line "$copy_root/$SCHEMA_TS_RELATIVE" || {
        report_case 1 "setup: edit $SCHEMA_TS_RELATIVE" "no content line could be deleted"
        return
    }
    run_drift_script "$copy_root" "$output_file"
    exit_code=$?
    outcome=0
    [ "$exit_code" -eq 1 ] || outcome=1
    report_case "$outcome" "$case_name exits 1" "exit $exit_code; output: $(cat "$output_file")"
    report_names_only "$output_file" "$SCHEMA_TS_RELATIVE" "$OPENAPI_RELATIVE" "$case_name"
}

# A hand edit to only the committed OpenAPI document fails and names openapi.yaml alone: the
# script generates the types from a fresh export, so the committed schema.ts still matches.
# Arguments: none.
test_document_only_edit_names_document_alone() {
    local copy_root="$WORK_DIRECTORY/document-edited"
    local output_file="$WORK_DIRECTORY/document-edited.out"
    local case_name="document-only edit"
    local exit_code outcome
    prepare_case_copy "$copy_root" "$case_name" || return
    change_committed_document_title "$copy_root" || {
        report_case 1 "setup: edit $OPENAPI_RELATIVE" "no info title line found"
        return
    }
    run_drift_script "$copy_root" "$output_file"
    exit_code=$?
    outcome=0
    [ "$exit_code" -eq 1 ] || outcome=1
    report_case "$outcome" "$case_name exits 1" "exit $exit_code; output: $(cat "$output_file")"
    report_names_only "$output_file" "$OPENAPI_RELATIVE" "$SCHEMA_TS_RELATIVE" "$case_name"
}

# After the HealthLiveness field is added, the output carries a diff line with the new field,
# and regenerating both committed files brings the script back to exit 0.
# Arguments: none.
test_schema_change_diff_and_regeneration() {
    local copy_root="$WORK_DIRECTORY/regenerated"
    local output_file="$WORK_DIRECTORY/regenerated-drift.out"
    local rerun_output_file="$WORK_DIRECTORY/regenerated-rerun.out"
    local case_name="drift diff and regeneration"
    local exit_code outcome
    prepare_case_copy "$copy_root" "$case_name" || return
    add_field_to_health_liveness "$copy_root" || {
        report_case 1 "setup: add a field to HealthLiveness" "$HEALTH_SCHEMA_RELATIVE not editable"
        return
    }
    run_drift_script "$copy_root" "$output_file"
    outcome=0
    grep -vE '^(\+\+\+|---) ' "$output_file" | grep -qE '^[+-].*[^[:alnum:]_]version[^[:alnum:]_]' || outcome=1
    report_case "$outcome" "drift output shows a diff line with the added field version" \
        "output: $(cat "$output_file")"
    regenerate_committed_contract "$copy_root" || {
        report_case 1 "setup: regenerate the committed contract" "a generator failed"
        return
    }
    run_drift_script "$copy_root" "$rerun_output_file"
    exit_code=$?
    outcome=0
    [ "$exit_code" -eq 0 ] || outcome=1
    report_case "$outcome" "regenerated contract exits 0" \
        "exit $exit_code; output: $(cat "$rerun_output_file")"
}

# An unmodified copy still exits 0 with APP_NAME set: the document must not read the app name
# from the environment, or a developer's local setting would show up as drift.
# Arguments: none.
test_app_name_does_not_change_document() {
    local copy_root="$WORK_DIRECTORY/renamed"
    local output_file="$WORK_DIRECTORY/renamed.out"
    local case_name="unmodified tree with APP_NAME set exits 0"
    local exit_code outcome
    prepare_case_copy "$copy_root" "$case_name" || return
    (
        export APP_NAME=renamed-app
        run_drift_script "$copy_root" "$output_file"
    )
    exit_code=$?
    outcome=0
    [ "$exit_code" -eq 0 ] || outcome=1
    report_case "$outcome" "$case_name" "exit $exit_code; output: $(cat "$output_file")"
}

test_unmodified_tree_passes
test_schema_change_without_regeneration_fails
test_types_only_edit_names_types_alone
test_document_only_edit_names_document_alone
test_schema_change_diff_and_regeneration
test_app_name_does_not_change_document

if [ "$FAILED_CASE_COUNT" -gt 0 ]; then
    echo "$FAILED_CASE_COUNT case(s) failed"
    exit 1
fi
echo "all cases passed"
