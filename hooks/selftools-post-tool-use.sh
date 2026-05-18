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

# Ensure AIDS_AGENT_ID is exported for the binary
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
exec "$SELFTOOLS_BIN" hook post-tool-use
