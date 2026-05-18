#!/usr/bin/env bash
# AIDS (Agent-ID System) — Shared shell functions for all hook wrappers.
# Source this file: source "$(dirname "$0")/_aid_common.sh"
# Provides: aid_detect_runtime, aid_resolve_agent_id, aid_find_bin
set -euo pipefail

# Resolve AIDS_RUNTIME from env or script filename.
aid_detect_runtime() {
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
}

# Resolve AIDS_AGENT_ID from env → session file.
# Exports AIDS_AGENT_ID if found.
aid_resolve_agent_id() {
  if [ -z "${AIDS_AGENT_ID:-}" ] && [ -z "${AID_AGENT_ID:-}" ] && [ -z "${SELFTOOLS_AGENT_ID:-}" ]; then
    local _aid_session_file="${HOME}/.aids/sessions/${AIDS_SESSION_ID:-}.json"
    if [ -n "${AIDS_SESSION_ID:-}" ] && [ -f "$_aid_session_file" ]; then
      local _aid_val
      _aid_val=$(grep '"agent_id"' "$_aid_session_file" 2>/dev/null | sed 's/.*: *"\([^"]*\)".*/\1/' | head -1 || true)
      if [ -n "$_aid_val" ]; then
        export AIDS_AGENT_ID="$_aid_val"
      fi
    fi
  fi
}

# Resolve SELFTOOLS_BIN path. Prints the binary path to stdout.
aid_find_bin() {
  local bin="${SELFTOOLS_BIN:-$HOME/.local/bin/selftools}"
  if [ ! -x "$bin" ]; then
    bin="${AIDS_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}/bin/selftools"
  fi
  echo "$bin"
}
