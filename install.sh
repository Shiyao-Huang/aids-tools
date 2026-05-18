#!/usr/bin/env bash
# AIDS (Agent-ID System) — one-line installer
# Usage:
#   curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
#   ./install.sh --source .
#   ./install.sh --uninstall
set -euo pipefail

APP="aids"
LEGACY_APP="selftools"
ZH_APP="AIDS (Agent-ID System)"
REPO_DEFAULT="https://github.com/Shiyao-Huang/aids-tools.git"
REPO="${AIDS_REPO:-${AID_REPO:-${SELFTOOLS_REPO:-$REPO_DEFAULT}}}"
INSTALL_DIR="${AIDS_INSTALL_DIR:-${AID_INSTALL_DIR:-${SELFTOOLS_INSTALL_DIR:-$HOME/.aids/selftools}}}"
DATA_DIR="${AIDS_DATA_DIR:-${AIDS_HOME:-${AID_DATA_DIR:-${AID_HOME:-${SELFTOOLS_DATA_DIR:-${ZHUYI_DATA_DIR:-$HOME/.aids}}}}}}"
BIN_DIR="${AIDS_BIN_DIR:-${SELFTOOLS_BIN_DIR:-$HOME/.local/bin}}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_HOME="${CODEX_HOME:-}"
SOURCE_DIR="${SELFTOOLS_SOURCE_DIR:-}"
DRY_RUN=0
UNINSTALL=0
PURGE_DATA=0
DO_CLAUDE=1
DO_CODEX=1
DO_MCP=1

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }
error() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
$APP / $ZH_APP installer

Usage:
  ./install.sh [options]
  curl -sfL <raw install.sh URL> | bash -s -- [options]

Options:
  --uninstall            Remove hook/config entries and installed binaries
  --purge-data           With --uninstall, also remove DATA_DIR (traces/sessions)
  --dry-run              Print planned actions without writing
  --source DIR           Install from an already checked out source directory
  --repo URL             Git repo to clone/update when not installing from source
  --install-dir DIR      Installation directory (default: $INSTALL_DIR)
  --data-dir DIR         Trace/session/timeline data directory (default: $DATA_DIR)
  --bin-dir DIR          Symlink/wrapper directory (default: $BIN_DIR)
  --claude-home DIR      Claude Code home (default: $CLAUDE_HOME)
  --codex-home DIR       Codex home (default: detected or ~/.codex)
  --no-claude            Skip ~/.claude hook registration
  --no-codex             Skip ~/.codex hook registration
  --no-mcp               Skip MCP wrapper registration
  --with-gitnexus        Enable GitNexus code-graph awareness (default: auto-detect)
  --without-gitnexus     Disable GitNexus integration
  -h, --help             Show this help

Environment overrides:
  AIDS_REPO/AID_REPO/SELFTOOLS_REPO, AIDS_INSTALL_DIR/AID_INSTALL_DIR/SELFTOOLS_INSTALL_DIR,
  AIDS_DATA_DIR/AIDS_HOME/AID_DATA_DIR/AID_HOME/SELFTOOLS_DATA_DIR/ZHUYI_DATA_DIR, AIDS_BIN_DIR/SELFTOOLS_BIN_DIR,
  CLAUDE_HOME, CODEX_HOME.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) UNINSTALL=1 ;;
    --purge-data) PURGE_DATA=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --source) SOURCE_DIR="${2:?--source requires DIR}"; shift ;;
    --repo) REPO="${2:?--repo requires URL}"; shift ;;
    --install-dir) INSTALL_DIR="${2:?--install-dir requires DIR}"; shift ;;
    --data-dir) DATA_DIR="${2:?--data-dir requires DIR}"; shift ;;
    --bin-dir) BIN_DIR="${2:?--bin-dir requires DIR}"; shift ;;
    --claude-home) CLAUDE_HOME="${2:?--claude-home requires DIR}"; shift ;;
    --codex-home) CODEX_HOME="${2:?--codex-home requires DIR}"; shift ;;
    --no-claude) DO_CLAUDE=0 ;;
    --no-codex) DO_CODEX=0 ;;
    --no-mcp) DO_MCP=0 ;;
    --with-gitnexus) WITH_GITNEXUS=1 ;;
    --without-gitnexus) WITH_GITNEXUS=0 ;;
    -h|--help) usage; exit 0 ;;
    *) error "Unknown option: $1" ;;
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
[ -n "$CODEX_HOME" ] && CODEX_HOME="$(expand_path "$CODEX_HOME")"
[ -n "$SOURCE_DIR" ] && SOURCE_DIR="$(expand_path "$SOURCE_DIR")"

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run_shell() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] %s\n' "$*"
  else
    eval "$@"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || error "$1 is required."
}

detect_codex_home() {
  if [ -n "${CODEX_HOME:-}" ]; then
    printf '%s\n' "$CODEX_HOME"
    return
  fi
  local codex_bin codex_root maybe
  codex_bin="$(command -v codex 2>/dev/null || true)"
  if [ -n "$codex_bin" ]; then
    codex_root="$(dirname "$(dirname "$codex_bin")")"
    maybe="$codex_root/.codex"
    if [ -d "$maybe" ]; then
      printf '%s\n' "$maybe"
      return
    fi
  fi
  if [ -d "${XDG_CONFIG_HOME:-$HOME/.config}/codex" ]; then
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/codex"
    return
  fi
  printf '%s\n' "$HOME/.codex"
}

CODEX_HOME="$(detect_codex_home)"

self_source_dir() {
  if [ -n "$SOURCE_DIR" ] && [ -x "$SOURCE_DIR/bin/selftools" ]; then
    printf '%s\n' "$SOURCE_DIR"
    return 0
  fi
  # Works when install.sh is run from a checkout. When curl|bash is used,
  # BASH_SOURCE is not a real repo path and this branch simply won't match.
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd -P 2>/dev/null || true)"
  if [ -n "$script_dir" ] && [ -x "$script_dir/bin/selftools" ]; then
    printf '%s\n' "$script_dir"
    return 0
  fi
  return 1
}

copy_source_tree() {
  local src="$1"
  info "Installing from source: $src"
  run mkdir -p "$INSTALL_DIR"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] copy bin hooks wrappers lib schemas packaging docs README.md install.sh to %q\n' "$INSTALL_DIR"
    return
  fi
  if [ "$(cd "$src" && pwd -P)" = "$(mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd -P)" ]; then
    ok "Source is already install dir: $INSTALL_DIR"
    return
  fi
  local items=()
  local item
  for item in bin hooks wrappers lib schemas packaging docs README.md install.sh; do
    [ -e "$src/$item" ] && items+=("$item")
  done
  (cd "$src" && tar -cf - "${items[@]}") | (cd "$INSTALL_DIR" && tar -xf -)
}

clone_or_update() {
  require_cmd git
  if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR"
    if [ "$DRY_RUN" -eq 1 ]; then
      printf '[DRY-RUN] git -C %q fetch/reset origin/main\n' "$INSTALL_DIR"
    else
      git -C "$INSTALL_DIR" fetch origin
      git -C "$INSTALL_DIR" reset --hard origin/main
    fi
  else
    info "Cloning $REPO to $INSTALL_DIR"
    run rm -rf "$INSTALL_DIR"
    run mkdir -p "$(dirname "$INSTALL_DIR")"
    run git clone --depth 1 "$REPO" "$INSTALL_DIR"
  fi
}

install_payload() {
  local src
  if src="$(self_source_dir)"; then
    copy_source_tree "$src"
  else
    clone_or_update
  fi
  run chmod +x "$INSTALL_DIR/bin/selftools" "$INSTALL_DIR/bin/selftools-mcp" "$INSTALL_DIR"/hooks/*.sh "$INSTALL_DIR"/wrappers/*
}

ensure_gitnexus() {
  if [ "${WITH_GITNEXUS:-}" = "1" ]; then
    if command -v gitnexus >/dev/null 2>&1 || command -v npx >/dev/null 2>&1; then
      info "GitNexus integration: enabled"
    else
      warn "GitNexus requested but neither gitnexus nor npx found; integration will be inactive"
    fi
  elif [ "${WITH_GITNEXUS:-}" = "0" ]; then
    info "GitNexus integration: disabled by flag"
  else
    if command -v gitnexus >/dev/null 2>&1; then
      info "GitNexus integration: auto-detected gitnexus binary"
    else
      info "GitNexus integration: not detected (use --with-gitnexus to enable)"
    fi
  fi
}

install_bins() {
  ensure_gitnexus
  info "Installing CLI shims into $BIN_DIR"
  run mkdir -p "$BIN_DIR"
  run ln -sf "$INSTALL_DIR/bin/selftools" "$BIN_DIR/selftools"
  run ln -sf "$INSTALL_DIR/bin/selftools" "$BIN_DIR/aids"
  run ln -sf "$INSTALL_DIR/bin/selftools" "$BIN_DIR/aid"
  run ln -sf "$INSTALL_DIR/bin/selftools-mcp" "$BIN_DIR/selftools-mcp"
  run ln -sf "$INSTALL_DIR/bin/selftools-mcp" "$BIN_DIR/aids-mcp"
  run ln -sf "$INSTALL_DIR/bin/selftools-mcp" "$BIN_DIR/aid-mcp"
  run ln -sf "$INSTALL_DIR/wrappers/claude-selftools" "$BIN_DIR/claude-selftools"
  run ln -sf "$INSTALL_DIR/wrappers/codex-selftools" "$BIN_DIR/codex-selftools"
  run ln -sf "$INSTALL_DIR/wrappers/aids-run" "$BIN_DIR/aids-run"
  run ln -sf "$INSTALL_DIR/wrappers/aids-bash" "$BIN_DIR/aids-bash"
  run ln -sf "$INSTALL_DIR/wrappers/aid-run" "$BIN_DIR/aid-run"
  run ln -sf "$INSTALL_DIR/wrappers/aid-bash" "$BIN_DIR/aid-bash"
}

install_runtime_hooks() {
  local runtime_home="$1"
  local runtime_name="$2"
  local hook_dir="$runtime_home/hooks"
  info "Dropping $runtime_name hook scripts into $hook_dir"
  run mkdir -p "$hook_dir"
  run install -m 755 "$INSTALL_DIR/hooks/selftools-session-start.sh" "$hook_dir/selftools-session-start.sh"
  run install -m 755 "$INSTALL_DIR/hooks/selftools-pre-tool-use.sh" "$hook_dir/selftools-pre-tool-use.sh"
  run install -m 755 "$INSTALL_DIR/hooks/selftools-post-tool-use.sh" "$hook_dir/selftools-post-tool-use.sh"
}

configure_claude_hooks() {
  [ "$DO_CLAUDE" -eq 1 ] || return 0
  local settings="$CLAUDE_HOME/settings.json"
  local hook_dir="$CLAUDE_HOME/hooks"
  install_runtime_hooks "$CLAUDE_HOME" "Claude Code"
  info "Registering Claude Code hooks in $settings"
  run mkdir -p "$CLAUDE_HOME"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] merge AIDS hooks into %q\n' "$settings"
    return
  fi
  CLAUDE_SETTINGS="$settings" CLAUDE_HOOK_DIR="$hook_dir" AIDS_DATA_DIR="$DATA_DIR" AIDS_HOME="$DATA_DIR" AID_DATA_DIR="$DATA_DIR" AID_HOME="$DATA_DIR" SELFTOOLS_DATA_DIR="$DATA_DIR" python3 <<'PY'
import json, os, shlex
from pathlib import Path
settings = Path(os.environ["CLAUDE_SETTINGS"])
hook_dir = Path(os.environ["CLAUDE_HOOK_DIR"])
settings.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
except json.JSONDecodeError:
    backup = settings.with_suffix(settings.suffix + ".selftools-bak")
    backup.write_text(settings.read_text(encoding="utf-8"), encoding="utf-8")
    data = {}

def clean_hooks(obj):
    hooks = obj.get("hooks") or {}
    for event, groups in list(hooks.items()):
        new_groups = []
        for group in groups if isinstance(groups, list) else []:
            handlers = group.get("hooks") or []
            handlers = [h for h in handlers if "selftools" not in str(h.get("command", ""))]
            if handlers:
                group = dict(group)
                group["hooks"] = handlers
                new_groups.append(group)
        if new_groups:
            hooks[event] = new_groups
        else:
            hooks.pop(event, None)
    obj["hooks"] = hooks

clean_hooks(data)
hooks = data.setdefault("hooks", {})

def add(event, matcher, script, status):
    cmd = shlex.quote(str(hook_dir / script))
    hooks.setdefault(event, []).append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": cmd, "statusMessage": status}]
    })

add("SessionStart", "startup|resume|clear|compact", "selftools-session-start.sh", "Registering AIDS session")
add("PreToolUse", "Read|Edit|Write|MultiEdit|Bash|NotebookEdit", "selftools-pre-tool-use.sh", "Checking AIDS trace chain")
add("PostToolUse", "Read|Edit|Write|MultiEdit|Bash|NotebookEdit", "selftools-post-tool-use.sh", "Recording AIDS trace")
settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  ok "Claude Code hooks registered"
}

configure_codex_hooks() {
  [ "$DO_CODEX" -eq 1 ] || return 0
  local hooks_json="$CODEX_HOME/hooks.json"
  local hook_dir="$CODEX_HOME/hooks"
  install_runtime_hooks "$CODEX_HOME" "Codex"
  info "Registering Codex hooks in $hooks_json"
  run mkdir -p "$CODEX_HOME"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] merge AIDS hooks into %q\n' "$hooks_json"
    return
  fi
  CODEX_HOOKS_JSON="$hooks_json" CODEX_HOOK_DIR="$hook_dir" python3 <<'PY'
import json, os, shlex
from pathlib import Path
hooks_path = Path(os.environ["CODEX_HOOKS_JSON"])
hook_dir = Path(os.environ["CODEX_HOOK_DIR"])
hooks_path.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_path.exists() else {}
except json.JSONDecodeError:
    backup = hooks_path.with_suffix(hooks_path.suffix + ".selftools-bak")
    backup.write_text(hooks_path.read_text(encoding="utf-8"), encoding="utf-8")
    data = {}

def clean_hooks(obj):
    hooks = obj.get("hooks") or {}
    for event, groups in list(hooks.items()):
        new_groups = []
        for group in groups if isinstance(groups, list) else []:
            handlers = group.get("hooks") or []
            handlers = [h for h in handlers if "selftools" not in str(h.get("command", ""))]
            if handlers:
                group = dict(group)
                group["hooks"] = handlers
                new_groups.append(group)
        if new_groups:
            hooks[event] = new_groups
        else:
            hooks.pop(event, None)
    obj["hooks"] = hooks

clean_hooks(data)
hooks = data.setdefault("hooks", {})

def add(event, matcher, script, status):
    cmd = shlex.quote(str(hook_dir / script))
    group = {"hooks": [{"type": "command", "command": cmd, "statusMessage": status}]}
    if matcher:
        group["matcher"] = matcher
    hooks.setdefault(event, []).append(group)

add("SessionStart", "startup|resume|clear", "selftools-session-start.sh", "Registering AIDS session")
# Codex maps apply_patch to Edit/Write aliases, but keeping apply_patch explicit helps old builds.
add("PreToolUse", "Bash|apply_patch|Edit|Write|Read|NotebookEdit|mcp__.*", "selftools-pre-tool-use.sh", "Checking AIDS trace chain")
add("PostToolUse", "Bash|apply_patch|Edit|Write|Read|NotebookEdit|mcp__.*", "selftools-post-tool-use.sh", "Recording AIDS trace")
hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  ok "Codex hooks registered"
}

configure_codex_mcp() {
  [ "$DO_CODEX" -eq 1 ] || return 0
  [ "$DO_MCP" -eq 1 ] || return 0
  local config="$CODEX_HOME/config.toml"
  local mcp="$INSTALL_DIR/bin/selftools-mcp"
  info "Registering Codex MCP wrapper tools in $config"
  run mkdir -p "$CODEX_HOME"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] add [mcp_servers.aids] to %q\n' "$config"
    return
  fi
CODEX_CONFIG="$config" SELFTOOLS_MCP="$mcp" AIDS_DATA_DIR="$DATA_DIR" AIDS_GITNEXUS="${WITH_GITNEXUS:-}" AIDS_HOME="$DATA_DIR" AID_DATA_DIR="$DATA_DIR" AID_HOME="$DATA_DIR" SELFTOOLS_DATA_DIR="$DATA_DIR" python3 <<'PY'
import os, re
from pathlib import Path
config = Path(os.environ["CODEX_CONFIG"])
mcp = os.environ["SELFTOOLS_MCP"]
data_dir = os.environ.get("AIDS_DATA_DIR") or os.environ.get("AIDS_HOME") or os.environ.get("AID_DATA_DIR") or os.environ["SELFTOOLS_DATA_DIR"]
config.parent.mkdir(parents=True, exist_ok=True)
text = config.read_text(encoding="utf-8") if config.exists() else ""
text = re.sub(r"\n?# (?:selftools|AIDS) MCP server BEGIN\n.*?# (?:selftools|AIDS) MCP server END\n?", "\n", text, flags=re.S)
# Also remove any unmarked [mcp_servers.aids] block from older installs
text = re.sub(r"\n?\[mcp_servers\.aids\][^\[]*", "\n", text)

def toml_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
block = "\n# AIDS MCP server BEGIN\n"
block += "[mcp_servers.aids]\n"
block += f"command = {toml_str(mcp)}\n"
block += f"env = {{ AIDS_DATA_DIR = {toml_str(data_dir)}, AIDS_HOME = {toml_str(data_dir)}, AID_DATA_DIR = {toml_str(data_dir)}, AID_HOME = {toml_str(data_dir)}, SELFTOOLS_DATA_DIR = {toml_str(data_dir)}, ZHUYI_DATA_DIR = {toml_str(data_dir)} }}\n"
block += "# AIDS MCP server END\n"
config.write_text(text.rstrip() + block, encoding="utf-8")
PY
  ok "Codex MCP server registered as aids"
}

configure_claude_mcp() {
  [ "$DO_CLAUDE" -eq 1 ] || return 0
  [ "$DO_MCP" -eq 1 ] || return 0
  local mcp="$INSTALL_DIR/bin/selftools-mcp"
  info "Registering Claude Code MCP wrapper tools (best effort)"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] claude mcp add --scope user aids -- %q\n' "$mcp"
    return
  fi
  if command -v claude >/dev/null 2>&1; then
    # Syntax follows Claude Code's user-scoped stdio MCP convention. Failure is non-fatal because
    # hooks still install and some Claude builds require interactive trust/managed config.
    claude mcp remove --scope user aids >/dev/null 2>&1 || true
    claude mcp remove --scope user selftools >/dev/null 2>&1 || true
    if claude mcp add --scope user aids -- "$mcp" >/dev/null 2>&1; then
      ok "Claude MCP server registered as aids"
    else
      warn "Could not auto-register Claude MCP. Hooks are installed; run: claude mcp add --scope user aids -- $mcp"
    fi
  else
    warn "claude binary not found; hooks/settings were written but MCP auto-registration was skipped"
  fi
}

init_data_dir() {
  info "Initializing data store at $DATA_DIR"
  run mkdir -p "$DATA_DIR/sessions" "$DATA_DIR/traces" "$DATA_DIR/timeline" "$DATA_DIR/index" "$DATA_DIR/ratings" "$DATA_DIR/pending" "$DATA_DIR/locks" "$DATA_DIR/logs"
}

remove_json_hooks() {
  local path="$1"
  [ -f "$path" ] || return 0
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] remove AIDS/selftools hook handlers from %q\n' "$path"
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
    kept_groups = []
    for group in groups if isinstance(groups, list) else []:
        handlers = [h for h in (group.get("hooks") or []) if "selftools" not in str(h.get("command", ""))]
        if handlers:
            g = dict(group); g["hooks"] = handlers; kept_groups.append(g)
    if kept_groups:
        hooks[event] = kept_groups
    else:
        hooks.pop(event, None)
if hooks:
    data["hooks"] = hooks
else:
    data.pop("hooks", None)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

remove_codex_mcp_block() {
  local config="$CODEX_HOME/config.toml"
  [ -f "$config" ] || return 0
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] remove AIDS/selftools MCP marker block from %q\n' "$config"
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

uninstall_all() {
  info "Uninstalling $APP / $ZH_APP"
  remove_json_hooks "$CLAUDE_HOME/settings.json"
  remove_json_hooks "$CODEX_HOME/hooks.json"
  remove_codex_mcp_block
  if [ "$DRY_RUN" -eq 0 ] && command -v claude >/dev/null 2>&1; then
    claude mcp remove --scope user aids >/dev/null 2>&1 || true
    claude mcp remove --scope user selftools >/dev/null 2>&1 || true
  fi
  run rm -f "$CLAUDE_HOME/hooks/selftools-session-start.sh" "$CLAUDE_HOME/hooks/selftools-pre-tool-use.sh" "$CLAUDE_HOME/hooks/selftools-post-tool-use.sh"
  run rm -f "$CODEX_HOME/hooks/selftools-session-start.sh" "$CODEX_HOME/hooks/selftools-pre-tool-use.sh" "$CODEX_HOME/hooks/selftools-post-tool-use.sh"
  run rm -f "$BIN_DIR/selftools" "$BIN_DIR/aids" "$BIN_DIR/aid" "$BIN_DIR/selftools-mcp" "$BIN_DIR/aids-mcp" "$BIN_DIR/aid-mcp" "$BIN_DIR/claude-selftools" "$BIN_DIR/codex-selftools" "$BIN_DIR/aids-run" "$BIN_DIR/aids-bash" "$BIN_DIR/aid-run" "$BIN_DIR/aid-bash"
  # Remove identity artifacts from current directory and data dir
  for f in .identity AIDS_IDENTITY.md; do
    run rm -f "$f"
  done
  if [ -L ".current" ]; then
    _target="$(readlink ".current" 2>/dev/null || true)"
    if echo "$_target" | grep -q "aids\|selftools" 2>/dev/null; then
      run rm -f ".current"
    fi
  fi
  if [ -d "$DATA_DIR" ]; then
    find "$DATA_DIR" -name ".identity" -type f 2>/dev/null | while read -r _f; do
      run rm -f "$_f"
    done
  fi
  run rm -rf "$INSTALL_DIR"
  if [ "$PURGE_DATA" -eq 1 ]; then
    run rm -rf "$DATA_DIR"
  else
    warn "Leaving trace/session data in $DATA_DIR (use --purge-data to remove)"
  fi
  ok "$APP uninstalled"
}

post_install_summary() {
  cat <<SUMMARY

${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
${GREEN} $APP / $ZH_APP installed successfully${NC}
${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}

Installed files:
  CLI:          $BIN_DIR/aids (legacy aliases: $BIN_DIR/aid, $BIN_DIR/selftools)
  MCP server:   $BIN_DIR/aids-mcp (legacy aliases: $BIN_DIR/aid-mcp, $BIN_DIR/selftools-mcp)
  Bash wrapper: $BIN_DIR/aids-run and $BIN_DIR/aids-bash (legacy: aid-run/aid-bash)
  Data store:   $DATA_DIR
  Claude hooks: $CLAUDE_HOME/hooks/selftools-*.sh
  Codex hooks:  $CODEX_HOME/hooks/selftools-*.sh

Runtime registration:
  Claude Code settings: $CLAUDE_HOME/settings.json
  Codex hooks:          $CODEX_HOME/hooks.json
  Codex MCP config:     $CODEX_HOME/config.toml

Session-ID env injection:
  Claude: SessionStart writes AIDS_SESSION_ID/AID_SESSION_ID/SESSION_ID plus legacy aliases to CLAUDE_ENV_FILE.
  Codex:  hooks use Codex session_id directly; use '$BIN_DIR/codex-selftools' to launch with env injection.

Try:
  aids doctor
  aids register-session --runtime codex --role implementer --goal "test install"
  aids who-touched README.md
  aids-run -- echo "manual bash command traced"

To uninstall:
  $INSTALL_DIR/install.sh --uninstall

${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
SUMMARY
}

main() {
  if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_all
    exit 0
  fi

  info "$APP / $ZH_APP installer"
  info "Modeled after clone/update + config registration curl|bash installers (claude-for-codex style)."
  require_cmd python3
  install_payload
  init_data_dir
  install_bins
  configure_claude_hooks
  configure_codex_hooks
  configure_codex_mcp
  configure_claude_mcp
  if [ "$DRY_RUN" -eq 0 ]; then
    CLAUDE_HOME="$CLAUDE_HOME" CODEX_HOME="$CODEX_HOME" AIDS_DATA_DIR="$DATA_DIR" AIDS_HOME="$DATA_DIR" AID_DATA_DIR="$DATA_DIR" AID_HOME="$DATA_DIR" SELFTOOLS_DATA_DIR="$DATA_DIR" \
      "$INSTALL_DIR/bin/selftools" --data-dir "$DATA_DIR" doctor >/dev/null 2>&1 || true
  fi
  post_install_summary
}

main "$@"
