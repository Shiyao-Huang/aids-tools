#!/usr/bin/env bash
# AIDS (Agent-ID System) — PostToolUse shell wrapper
# Thin wrapper called by Claude Code's settings.json hooks.
# Delegates to the Node.js implementation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec node "${SCRIPT_DIR}/post_tool_use.js"
