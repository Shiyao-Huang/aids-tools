#!/usr/bin/env bash
# AIDS (Agent-ID System) — SessionStart shell wrapper
# Resolves identity + infers defaults → delegates to binary.
set -euo pipefail
source "$(dirname "$0")/_aid_common.sh"
aid_detect_runtime
aid_resolve_agent_id

# Auto-infer display_name: git user.name → whoami
if [ -z "${AIDS_DISPLAY_NAME:-}" ] && [ -z "${AHA_SESSION_NAME:-}" ] && [ -z "${AID_DISPLAY_NAME:-}" ] && [ -z "${SELFTOOLS_DISPLAY_NAME:-}" ]; then
  _aids_git_name="$(git config user.name 2>/dev/null || true)"
  if [ -n "$_aids_git_name" ]; then
    export AIDS_DISPLAY_NAME="$_aids_git_name"
  else
    export AIDS_DISPLAY_NAME="$(whoami)"
  fi
  unset _aids_git_name
fi

# Auto-infer role
if [ -z "${AIDS_ROLE:-}" ] && [ -z "${AID_ROLE:-}" ] && [ -z "${AHA_AGENT_ROLE:-}" ] && [ -z "${ROLE:-}" ] && [ -z "${SELFTOOLS_ROLE:-}" ]; then
  export AIDS_ROLE="developer"
fi

# Auto-infer model
if [ -z "${AIDS_MODEL:-}" ] && [ -z "${AID_MODEL:-}" ] && [ -z "${SELFTOOLS_MODEL:-}" ]; then
  if [ -n "${CLAUDE_MODEL:-}" ]; then
    export AIDS_MODEL="$CLAUDE_MODEL"
  elif [ -n "${CODEX_MODEL:-}" ]; then
    export AIDS_MODEL="$CODEX_MODEL"
  fi
fi

exec "$(aid_find_bin)" hook session-start
