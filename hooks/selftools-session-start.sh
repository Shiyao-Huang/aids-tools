#!/usr/bin/env bash
set -euo pipefail
case "${AIDS_RUNTIME:-${SELFTOOLS_RUNTIME:-}}" in
  claude|codex) ;;
  *)
    case "$0" in
      *".codex"*) export AIDS_RUNTIME="codex" ;;
      *".claude"*) export AIDS_RUNTIME="claude" ;;
      *) export AIDS_RUNTIME="unknown" ;;
    esac
    ;;
esac
export SELFTOOLS_RUNTIME="${SELFTOOLS_RUNTIME:-$AIDS_RUNTIME}"

# ── Auto-infer identity for non-Aha managed sessions ──

# 1. AIDS_DISPLAY_NAME: fall back to git user.name, then whoami
if [ -z "${AIDS_DISPLAY_NAME:-}" ] && [ -z "${AHA_SESSION_NAME:-}" ] && [ -z "${AID_DISPLAY_NAME:-}" ] && [ -z "${SELFTOOLS_DISPLAY_NAME:-}" ]; then
  _aids_git_name="$(git config user.name 2>/dev/null || true)"
  if [ -n "$_aids_git_name" ]; then
    export AIDS_DISPLAY_NAME="$_aids_git_name"
  else
    export AIDS_DISPLAY_NAME="$(whoami)"
  fi
  unset _aids_git_name
fi

# 2. AIDS_ROLE: default to "developer"
if [ -z "${AIDS_ROLE:-}" ] && [ -z "${AID_ROLE:-}" ] && [ -z "${AHA_AGENT_ROLE:-}" ] && [ -z "${ROLE:-}" ] && [ -z "${SELFTOOLS_ROLE:-}" ]; then
  export AIDS_ROLE="developer"
fi

# 3. AIDS_MODEL: infer from runtime-specific env vars
if [ -z "${AIDS_MODEL:-}" ] && [ -z "${AID_MODEL:-}" ] && [ -z "${SELFTOOLS_MODEL:-}" ]; then
  if [ -n "${CLAUDE_MODEL:-}" ]; then
    export AIDS_MODEL="$CLAUDE_MODEL"
  elif [ -n "${CODEX_MODEL:-}" ]; then
    export AIDS_MODEL="$CODEX_MODEL"
  fi
fi

# 4. AIDS_AGENT_ID: export for downstream hooks (pre/post-tool-use)
if [ -z "${AIDS_AGENT_ID:-}" ] && [ -z "${AID_AGENT_ID:-}" ] && [ -z "${SELFTOOLS_AGENT_ID:-}" ]; then
  _aid_session_file="${HOME}/.aids/sessions/${AIDS_SESSION_ID:-}.json"
  if [ -n "${AIDS_SESSION_ID:-}" ] && [ -f "$_aid_session_file" ]; then
    _aid_val=$(grep '"agent_id"' "$_aid_session_file" 2>/dev/null | sed 's/.*: *"\([^"]*\)".*/\1/' | head -1 || true)
    if [ -n "$_aid_val" ]; then
      export AIDS_AGENT_ID="$_aid_val"
    fi
  fi
fi

SELFTOOLS_BIN="${SELFTOOLS_BIN:-$HOME/.local/bin/selftools}"
if [ ! -x "$SELFTOOLS_BIN" ]; then
  SELFTOOLS_BIN="${AIDS_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}/bin/selftools"
fi
exec "$SELFTOOLS_BIN" hook session-start
