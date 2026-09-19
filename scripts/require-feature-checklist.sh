#!/usr/bin/env bash
# require-feature-checklist.sh: the R-607 feature checklist, generalized from
# Doppelscript's scripts/require-feature-checklist.sh. When the branch ADDS a
# user-facing route relative to its base, the same branch must also change the
# features list, a user story, and an end-to-end spec; otherwise exit 1 with a
# report naming the triggering files and each missing artifact.
#
# Canonical copy: hooks/push-feature-docs-gate.sh runs THIS file in every
# repository at push time and never a repository's own copy (push gates do not
# execute target-repository code, 2026-07-31 security audit). repo-setup copies
# it into an application repository as scripts/require-feature-checklist.sh,
# where that repository's own git hook or CI may run it.
#
# Usage: require-feature-checklist.sh [base-ref], run with cwd inside the
# repository. Base: the argument, else FEATURE_CHECKLIST_BASE, else origin/main.
# Per-repository data in .enforce.json: {"productDocs": false} turns the check
# off; {"productDocs": {"extraTriggers": ["<ERE>", ...]}} adds trigger patterns,
# read as grep -E patterns and never evaluated.
#
# The trigger is deliberately narrow (Doppelscript's reasoning): an ADDED route
# file is the least ambiguous diff signal for a new user-facing flow. Feature
# work that adds no route does not trip it; that false negative is the accepted
# cost of a near-zero false-positive rate. Spec:
# docs/superpowers/specs/2026-09-18-product-docs-design.md.
set -uo pipefail

# Built-in triggers, one per stack, anchored at a path-segment boundary so a
# monorepo prefix (apps/client/web/) still matches.
BUILTIN_TRIGGERS=(
  '(^|/)(src/)?app/(.+/)?(page|route)\.(tsx|ts|jsx|js)$'
  '(^|/)app/pages/.+\.vue$'
  '(^|/)server/(api|routes)/.+\.(ts|js)$'
  '(^|/)app/routers/[^/]+\.py$'
  '(^|/)src/(routes|handlers)/.+\.(ts|js)$'
)
TEST_FILE_PATTERN='(\.(test|spec)\.[^/]+$)|(/__tests__/)|((^|/)test_[^/]+\.py$)|((^|/)__init__\.py$)'
STORY_PATTERN='^docs/user-stories/.+[.]md$'
E2E_PATTERN='(^|/)e2e/(.+/)?([^/]+\.(spec|test)\.(ts|js|mjs)|test_[^/]+\.py)$'

# is_check_disabled: true when .enforce.json sets productDocs to false. A
# missing jq means the opt-out cannot be read, so the check runs (a guard
# fails closed).
is_check_disabled() {
  [ -f .enforce.json ] && command -v jq >/dev/null 2>&1 \
    && jq -e '.productDocs == false' .enforce.json >/dev/null 2>&1
}

# list_extra_triggers: prints each valid productDocs.extraTriggers pattern;
# an invalid one is reported on stderr and dropped, so one bad entry never
# disables the built-in triggers.
list_extra_triggers() {
  [ -f .enforce.json ] && command -v jq >/dev/null 2>&1 || return 0
  local pattern
  jq -r '.productDocs.extraTriggers[]? // empty' .enforce.json 2>/dev/null | while IFS= read -r pattern; do
    [ -n "$pattern" ] || continue
    printf '' | grep -E -- "$pattern" >/dev/null 2>&1
    if [ $? -eq 2 ]; then
      echo "require-feature-checklist: ignoring invalid extraTriggers pattern in .enforce.json: $pattern" >&2
    else
      printf '%s\n' "$pattern"
    fi
  done
}

# find_triggers <added-files>: prints the added files that match a trigger and
# are not test files.
find_triggers() {
  local added="$1" pattern_args=() pattern
  for pattern in "${BUILTIN_TRIGGERS[@]}"; do pattern_args+=(-e "$pattern"); done
  while IFS= read -r pattern; do pattern_args+=(-e "$pattern"); done < <(list_extra_triggers)
  printf '%s\n' "$added" | grep -E "${pattern_args[@]}" | grep -vE "$TEST_FILE_PATTERN" || true
}

# list_missing_artifacts <changed-files>: prints one line per required
# artifact the branch did not change. Each check reads a here-string, never a
# pipe: under pipefail an early-exiting grep -q kills its upstream writer with
# SIGPIPE once the file list outgrows the pipe buffer, and the failed pipeline
# would report a present artifact as missing (PR #44 review).
list_missing_artifacts() {
  local changed="$1"
  grep -qxF 'docs/feature-list/features.md' <<<"$changed" \
    || echo "  docs/feature-list/features.md not updated (feature row and status)"
  awk -v story="$STORY_PATTERN" '$0 ~ story && $0 != "docs/user-stories/README.md" { found = 1 } END { exit !found }' <<<"$changed" \
    || echo "  no user story created or updated in docs/user-stories/ (README.md alone does not count)"
  grep -qE "$E2E_PATTERN" <<<"$changed" \
    || echo "  no e2e spec created or updated under e2e/"
}

# print_report <triggers> <missing>: the failure report on stdout.
print_report() {
  echo "R-607 feature checklist is incomplete for this branch."
  echo ""
  echo "  new user-facing route(s) on this branch:"
  printf '%s\n' "$1" | sed 's/^/    /'
  echo ""
  echo "  missing:"
  printf '%s\n' "$2"
  echo ""
  echo "If an existing story and spec already cover this flow, update them (tick the"
  echo "criterion, note the route) so the branch shows the coverage."
}

BASE_REF="${1:-${FEATURE_CHECKLIST_BASE:-origin/main}}"
git rev-parse --verify --quiet "$BASE_REF" >/dev/null || exit 0
MERGE_BASE=$(git merge-base "$BASE_REF" HEAD 2>/dev/null || true)
[ -n "$MERGE_BASE" ] || exit 0
[ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ] && exit 0
cd "$(git rev-parse --show-toplevel)" || exit 0
is_check_disabled && exit 0

ADDED=$(git diff --name-only --diff-filter=A "$MERGE_BASE"..HEAD 2>/dev/null || true)
TRIGGERS=$(find_triggers "$ADDED")
[ -n "$TRIGGERS" ] || exit 0

CHANGED=$(git diff --name-only "$MERGE_BASE"..HEAD 2>/dev/null || true)
MISSING=$(list_missing_artifacts "$CHANGED")
[ -n "$MISSING" ] || exit 0

print_report "$TRIGGERS" "$MISSING"
exit 1
