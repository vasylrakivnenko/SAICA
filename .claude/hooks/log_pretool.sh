#!/usr/bin/env bash
# SAICA-KG — Claude Code PreToolUse hook
#
# Reads a Claude Code hook event from stdin (JSON) and, IF the event is a
# denial, calls `python -m pipeline.supervision log` to append a JSONL line
# to .saica/prevention_log/<date>.jsonl. Otherwise it is a silent no-op so
# normal tool invocations are not slowed down.
#
# KG citations:
# - data/failure_modes/scope_creep.yml — primary FM tagged when CLAUDE.md's
#   plan-first / scope rule denies a tool call.
# - data/tools/semgrep.yml, data/tools/dependabot.yml — citation-style guide
#   for this header.
#
# Wire it in your local .claude/settings.local.json:
#   { "hooks": { "PreToolUse": [ { "command": ".claude/hooks/log_pretool.sh" } ] } }
#
# Detection rule: a denial event has  "decision": "deny"  somewhere in the
# JSON payload. We use a tolerant regex (jq is not assumed available).

set -euo pipefail

# Resolve the repo root from this script's location so the hook works no
# matter the cwd Claude Code invokes it from.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HOOK_DIR}/../.." && pwd)"

# Prefer the project venv, fall back to whatever python3 is on PATH.
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON_BIN}" ]]; then
    # No python available — silently no-op so we never block Claude Code.
    exit 0
fi

# Read the full event from stdin. Cap at 1 MiB to be safe.
PAYLOAD="$(head -c 1048576 || true)"

# Only act on denials. Tolerant of whitespace and quote style.
if [[ ! "${PAYLOAD}" =~ \"decision\"[[:space:]]*:[[:space:]]*\"deny\" ]]; then
    exit 0
fi

# Best-effort field extraction — falls back to "unknown" so a malformed
# payload still produces a usable event.
extract() {
    # $1 = JSON key
    local key="$1"
    local value
    value="$(printf '%s' "${PAYLOAD}" \
        | grep -oE "\"${key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
        | head -n1 \
        | sed -E "s/^\"${key}\"[[:space:]]*:[[:space:]]*\"(.*)\"$/\1/")"
    if [[ -z "${value}" ]]; then
        echo "unknown"
    else
        echo "${value}"
    fi
}

TOOL_NAME="$(extract tool_name)"
REASON="$(extract reason)"

# Truncate the detail so we never write a huge blob to the log.
DETAIL="tool=${TOOL_NAME}; reason=${REASON}"
DETAIL="${DETAIL:0:512}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m pipeline.supervision log \
    --tool-id "claude-code" \
    --failure-mode "scope_creep" \
    --mechanism "denied-pretooluse-via-claude-code-hook" \
    --detail "${DETAIL}" \
    --invoked-by "claude-code-hook" >/dev/null 2>&1 || true

# Always exit 0 — the hook's job is to *observe*, not to block.
exit 0
