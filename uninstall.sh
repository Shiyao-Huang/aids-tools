#!/usr/bin/env bash
# AIDS (Agent-ID System) — uninstaller
# Usage:
#   ./uninstall.sh              # Remove bins/hooks, keep data
#   ./uninstall.sh --purge-data # Remove everything including traces/sessions
#   ./uninstall.sh --dry-run    # Show what would be removed
set -euo pipefail

APP="aids"
ZH_NAME="AIDS (Agent-ID System)"
INSTALL_DIR="${AIDS_INSTALL_DIR:-${AID_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}}"
DATA_DIR="${AIDS_DATA_DIR:-${AIDS_HOME:-${AID_DATA_DIR:-${AID_HOME:-${SELFTOOLS_DATA_DIR:-$HOME/.aids}}}}}"
BIN_DIR="${AIDS_BIN_DIR:-${SELFTOOLS_BIN_DIR:-$HOME/.local/bin}}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_HOME="${CODEX_HOME:-}"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

DRY_RUN=0
PURGE_DATA=0

info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
ok()   { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }

usage() {
  cat <<USAGE
$APP / $ZH_NAME uninstaller

Usage:
  ./uninstall.sh [options]

Options:
  --purge-data   Also remove all trace/session/timeline data
  --dry-run      Show planned actions without executing
  -h, --help     Show this help

Default mode removes:
  - CLI symlinks from $BIN_DIR
  - Hook scripts from Claude/Codex homes
  - Hook registrations from settings.json / hooks.json
  - MCP server registrations
  - Installation directory ($INSTALL_DIR)
  - Identity files (.identity, .current, AIDS_IDENTITY.md)

Default mode preserves:
  - All trace/session/timeline data in $DATA_DIR

Use --purge-data to remove everything.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-data) PURGE_DATA=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) warn "Unknown option: $1" ;;
  esac
  shift
done

expand_path() {
  case "$1" in
    ~) printf '%s\n' "$HOME" ;;
    ~/*) printf '%s/%s\n' "$HOME" "${1#~/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

INSTALL_DIR="$(expand_path "$INSTALL_DIR")"
DATA_DIR="$(expand_path "$DATA_DIR")"
BIN_DIR="$(expand_path "$BIN_DIR")"
CLAUDE_HOME="$(expand_path "$CLAUDE_HOME")"
if [ -z "$CODEX_HOME" ]; then
  CODEX_HOME="$HOME/.codex"
fi
CODEX_HOME="$(expand_path "$CODEX_HOME")"

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@" 2>/dev/null || true
  fi
}

# --- Remove JSON hook registrations ---
remove_json_hooks() {
  local path="$1"
  [ -f "$path" ] || return 0
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] remove AIDS/selftools hooks from %q\n' "$path"
    return
  fi
  JSON_HOOK_PATH="$path" python3 <<'PY'
import json, os
from pathlib import Path
path = Path(os.environ["JSON_HOOK_PATH"])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
hooks = data.get("hooks") or {}
for event, groups in list(hooks.items()):
    kept = []
    for group in groups if isinstance(groups, list) else []:
        handlers = [h for h in (group.get("hooks") or []) if "selftools" not in str(h.get("command", ""))]
        if handlers:
            g = dict(group); g["hooks"] = handlers; kept.append(g)
    if kept:
        hooks[event] = kept
    else:
        hooks.pop(event, None)
if hooks:
    data["hooks"] = hooks
else:
    data.pop("hooks", None)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

# --- Remove Codex MCP block ---
remove_codex_mcp() {
  local config="$CODEX_HOME/config.toml"
  [ -f "$config" ] || return 0
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] remove AIDS MCP block from %q\n' "$config"
    return
  fi
  CODEX_CONFIG="$config" python3 <<'PY'
import os, re
from pathlib import Path
path = Path(os.environ["CODEX_CONFIG"])
text = path.read_text(encoding="utf-8")
text = re.sub(r"\n?# (?:selftools|AIDS) MCP server BEGIN\n.*?# (?:selftools|AIDS) MCP server END\n?", "\n", text, flags=re.S)
path.write_text(text.rstrip() + ("\n" if text.strip() else ""), encoding="utf-8")
PY
}

# --- Remove Claude MCP ---
remove_claude_mcp() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] claude mcp remove --scope user aids\n'
    return
  fi
  command -v claude >/dev/null 2>&1 || return 0
  claude mcp remove --scope user aids >/dev/null 2>&1 || true
  claude mcp remove --scope user selftools >/dev/null 2>&1 || true
}

# --- Remove identity files ---
remove_identity_files() {
  local project_dir="${1:-}"
  [ -z "$project_dir" ] && return 0
  # Remove per-session identity artifacts
  for f in .identity AIDS_IDENTITY.md; do
    if [ -f "$project_dir/$f" ]; then
      run rm -f "$project_dir/$f"
    fi
  done
  # Remove .current symlink if it points to an AIDS session
  if [ -L "$project_dir/.current" ]; then
    local target
    target="$(readlink "$project_dir/.current" 2>/dev/null || true)"
    if echo "$target" | grep -q "aids\|selftools" 2>/dev/null; then
      run rm -f "$project_dir/.current"
    fi
  fi
}

# --- Main uninstall ---
main() {
  info "Uninstalling $APP / $ZH_NAME"
  echo ""

  # 1. Remove hook registrations
  info "Removing hook registrations..."
  remove_json_hooks "$CLAUDE_HOME/settings.json"
  remove_json_hooks "$CODEX_HOME/hooks.json"
  ok "Hook registrations removed"

  # 2. Remove MCP registrations
  info "Removing MCP registrations..."
  remove_codex_mcp
  remove_claude_mcp
  ok "MCP registrations removed"

  # 3. Remove hook scripts
  info "Removing hook scripts..."
  for hook in selftools-session-start.sh selftools-pre-tool-use.sh selftools-post-tool-use.sh; do
    run rm -f "$CLAUDE_HOME/hooks/$hook"
    run rm -f "$CODEX_HOME/hooks/$hook"
  done
  ok "Hook scripts removed"

  # 4. Remove CLI symlinks
  info "Removing CLI symlinks from $BIN_DIR..."
  for name in selftools aids aid selftools-mcp aids-mcp aid-mcp claude-selftools codex-selftools aids-run aids-bash aid-run aid-bash; do
    run rm -f "$BIN_DIR/$name"
  done
  ok "CLI symlinks removed"

  # 5. Remove identity files from well-known locations
  info "Removing identity files..."
  remove_identity_files "."
  remove_identity_files "$HOME"
  # Clean up any stray .identity files in data dir subdirectories
  if [ -d "$DATA_DIR" ]; then
    find "$DATA_DIR" -name ".identity" -type f 2>/dev/null | while read -r f; do
      run rm -f "$f"
    done
  fi
  ok "Identity files removed"

  # 6. Remove installation directory
  if [ -d "$INSTALL_DIR" ]; then
    info "Removing installation directory: $INSTALL_DIR"
    run rm -rf "$INSTALL_DIR"
    ok "Installation directory removed"
  else
    info "Installation directory not found: $INSTALL_DIR (already removed)"
  fi

  # 7. Optionally remove data
  if [ "$PURGE_DATA" -eq 1 ]; then
    if [ -d "$DATA_DIR" ]; then
      warn "Purging all data: $DATA_DIR"
      run rm -rf "$DATA_DIR"
      ok "Data directory purged"
    else
      info "Data directory not found: $DATA_DIR"
    fi
  else
    echo ""
    if [ -d "$DATA_DIR" ]; then
      info "Preserving data in $DATA_DIR"
      info "  (use --purge-data to remove traces, sessions, timeline, ratings)"
    fi
  fi

  # Summary
  echo ""
  printf "%b━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%b\n" "$GREEN" "$NC"
  printf "%b %s / %s uninstalled%b\n" "$GREEN" "$APP" "$ZH_NAME" "$NC"
  printf "%b━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%b\n" "$GREEN" "$NC"

  if [ "$PURGE_DATA" -eq 0 ] && [ -d "$DATA_DIR" ]; then
    echo ""
    info "Data preserved at: $DATA_DIR"
    info "To fully remove: $0 --purge-data"
  fi

  echo ""
  info "Reinstall anytime: curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash"
}

main
