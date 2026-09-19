#!/usr/bin/env bash
# harness-bootstrap.sh: SessionStart hook written by the repo-setup skill
# (R-003, every session runs under the synced harness). In a Claude Code on
# the web session the container starts with no ~/.claude harness at all; this
# clones the agent-governance repository and runs its harness-sync hook, so
# the hooks, gates, skills, and rules apply from the first tool call. On a
# machine that already carries the harness (a laptop, or a container after the
# first run) it only re-syncs drift, through the same hook. Idempotent,
# non-interactive, never blocks the session: every failure is one
# additionalContext line and exit 0.
#
# git@github.com:nullvoidundefined/agent-governance.git is substituted by repo-setup from --harness-repo or from
# the origin of the checkout named in ~/.claude/.sync-source.
set -uo pipefail
HARNESS_REPO="git@github.com:nullvoidundefined/agent-governance.git"
CHECKOUT="${HARNESS_CHECKOUT:-$HOME/agent-governance}"

say() { jq -n --arg m "$1" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}' 2>/dev/null || true; }

if [ -f "$HOME/.claude/.sync-source" ] && [ -f "$HOME/.claude/hooks/harness-sync.sh" ]; then
  # Harness present: the user-level registration of harness-sync.sh handles
  # drift on its own; running it here too keeps a repo whose user settings
  # predate that registration covered.
  bash "$HOME/.claude/hooks/harness-sync.sh"
  exit 0
fi

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  say "harness-bootstrap (R-003): ~/.claude carries no synced harness and this is not a remote session, so nothing was cloned. Run ./sync.sh from your agent-governance checkout."
  exit 0
fi

if [ ! -f "$CHECKOUT/sync.sh" ]; then
  if ! git clone -q --depth 1 "$HARNESS_REPO" "$CHECKOUT" >/dev/null 2>&1; then
    say "harness-bootstrap (R-003): could not clone $HARNESS_REPO into $CHECKOUT, so this remote session runs WITHOUT the synced harness; treat every rule as manual."
    exit 0
  fi
fi
CLAUDE_CODE_REMOTE=true bash "$CHECKOUT/claude/hooks/harness-sync.sh" "$CHECKOUT"
exit 0
