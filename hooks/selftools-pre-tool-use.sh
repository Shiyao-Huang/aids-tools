#!/usr/bin/env bash
# AIDS (Agent-ID System) — PreToolUse shell wrapper
# Thin wrapper: resolves identity → delegates to binary.
set -euo pipefail
source "$(dirname "$0")/_aid_common.sh"
aid_detect_runtime
aid_resolve_agent_id
exec "$(aid_find_bin)" hook pre-tool-use
