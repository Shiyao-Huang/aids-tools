#!/usr/bin/env bash
# AIDS (Agent-ID System) — PostToolUse shell wrapper (Node.js delegation)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_aid_common.sh"
aid_resolve_agent_id
exec node "${SCRIPT_DIR}/post_tool_use.js"
