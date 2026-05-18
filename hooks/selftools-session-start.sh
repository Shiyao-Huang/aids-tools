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

SELFTOOLS_BIN="${SELFTOOLS_BIN:-$HOME/.local/bin/selftools}"
if [ ! -x "$SELFTOOLS_BIN" ]; then
  SELFTOOLS_BIN="${AIDS_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}/bin/selftools"
fi
exec "$SELFTOOLS_BIN" hook session-start
