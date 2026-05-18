#!/usr/bin/env bash
# AIDS (Agent-ID System) — PreToolUse shell wrapper
# Thin wrapper called by Claude Code's settings.json hooks.
# Delegates to the Node.js implementation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure AIDS_AGENT_ID is exported for the Node.js hook
if [ -z "${AIDS_AGENT_ID:-}" ] && [ -n "${AIDS_SESSION_ID:-}" ]; then
  _aid_session_file="${HOME}/.aids/sessions/${AIDS_SESSION_ID}.json"
  if [ -f "$_aid_session_file" ]; then
    _aid_val=$(grep '"agent_id"' "$_aid_session_file" 2>/dev/null | sed 's/.*: *"\([^"]*\)".*/\1/' | head -1 || true)
    if [ -n "$_aid_val" ]; then
      export AIDS_AGENT_ID="$_aid_val"
    fi
  fi
fi

exec node "${SCRIPT_DIR}/pre_tool_use.js"
