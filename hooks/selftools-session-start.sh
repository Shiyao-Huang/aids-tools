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
SELFTOOLS_BIN="${SELFTOOLS_BIN:-$HOME/.local/bin/selftools}"
if [ ! -x "$SELFTOOLS_BIN" ]; then
  SELFTOOLS_BIN="${AIDS_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}/bin/selftools"
fi
exec "$SELFTOOLS_BIN" hook session-start
