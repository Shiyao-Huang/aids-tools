#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AIDS Self-Iteration Script
#
# Runs `npx aha legion` with an AIDS-specific iteration prompt that:
#   1. Reads ratings/feedback from ~/.aids/ratings/
#   2. Analyzes trace history from ~/.aids/traces/
#   3. Identifies agent performance patterns & file conflicts
#   4. Generates targeted improvement suggestions
#
# Mode: DRY-RUN by default (report only, no push).
#       Set AIDS_AUTO_PUSH=1 to allow auto-push after iteration.
#
# Usage:
#   ./scripts/aids-legion-iterate.sh              # dry-run
#   AIDS_AUTO_PUSH=1 ./scripts/aids-legion-iterate.sh  # auto-push
#
# Scheduling (cron):
#   0 */4 * * * cd ~/Desktop/selftools && ./scripts/aids-legion-iterate.sh >> ~/.aids/logs/iterate.log 2>&1
#
# Scheduling (launchd — macOS):
#   See .aha/prompts/aids-iteration.md for plist example
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AIDS_HOME="${AIDS_HOME:-$HOME/.aids}"
PROMPT_FILE="$PROJECT_DIR/.aha/prompts/aids-iteration.md"
LOG_DIR="$AIDS_HOME/logs"

# ── Config ───────────────────────────────────────────────────────────────────
AUTO_PUSH="${AIDS_AUTO_PUSH:-0}"
LEGION_CMD="${AIDS_LEGION_CMD:-npx aha legion}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H%M%SZ")

# ── Logging ──────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [aids-iterate] $*"; }

# ── Pre-flight checks ───────────────────────────────────────────────────────
preflight() {
  if ! command -v npx &>/dev/null; then
    log "ERROR: npx not found. Install Node.js first."
    exit 1
  fi

  if [[ ! -f "$PROMPT_FILE" ]]; then
    log "ERROR: Iteration prompt not found at $PROMPT_FILE"
    log "Create .aha/prompts/aids-iteration.md first."
    exit 1
  fi

  mkdir -p "$AIDS_HOME"/{sessions,traces,index,ratings,logs,timeline}
}

# ── Gather context ───────────────────────────────────────────────────────────
gather_context() {
  local ctx_file="$LOG_DIR/iterate-context-${TIMESTAMP}.json"

  # Count traces (last 24h)
  local trace_count=0
  if [[ -d "$AIDS_HOME/traces" ]]; then
    while IFS= read -r f; do
      [[ -f "$f" ]] || continue
      trace_count=$((trace_count + $(wc -l < "$f" | tr -d ' ')))
    done < <(find "$AIDS_HOME/traces" -name '*.jsonl' -mtime -1 2>/dev/null)
  fi

  # Count ratings (last 24h)
  local rating_count=0
  local good_count=0 bad_count=0
  if [[ -d "$AIDS_HOME/ratings" ]]; then
    while IFS= read -r f; do
      [[ -f "$f" ]] || continue
      local lines
      lines=$(wc -l < "$f" | tr -d ' ')
      rating_count=$((rating_count + lines))
      good_count=$((good_count + $(grep -c '"score":"good"' "$f" 2>/dev/null || echo 0)))
      bad_count=$((bad_count + $(grep -c '"score":"bad"' "$f" 2>/dev/null || echo 0)))
    done < <(find "$AIDS_HOME/ratings" -name '*.jsonl' -mtime -1 2>/dev/null)
  fi

  # Active sessions
  local active_sessions=0
  if [[ -d "$AIDS_HOME/sessions" ]]; then
    active_sessions=$(grep -rl '"status": "active"' "$AIDS_HOME/sessions/" 2>/dev/null | wc -l | tr -d ' ')
  fi

  # Recent git changes
  local git_changes=0
  if git -C "$PROJECT_DIR" rev-parse --git-dir &>/dev/null; then
    git_changes=$(git -C "$PROJECT_DIR" log --oneline HEAD~10..HEAD 2>/dev/null | wc -l | tr -d ' ')
  fi

  cat > "$ctx_file" <<EOF
{
  "timestamp": "$TIMESTAMP",
  "auto_push": $AUTO_PUSH,
  "project_dir": "$PROJECT_DIR",
  "aids_home": "$AIDS_HOME",
  "trace_count_24h": $trace_count,
  "rating_count_24h": $rating_count,
  "good_ratings": $good_count,
  "bad_ratings": $bad_count,
  "active_sessions": $active_sessions,
  "recent_git_commits": $git_changes
}
EOF

  echo "$ctx_file"
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
  log "Starting AIDS self-iteration..."
  preflight

  local ctx_file
  ctx_file=$(gather_context)
  log "Context: $(cat "$ctx_file")"

  # Export context for the prompt to consume
  export AIDS_ITERATE_CONTEXT="$ctx_file"
  export AIDS_ITERATE_TIMESTAMP="$TIMESTAMP"
  export AIDS_ITERATE_PROMPT="$PROMPT_FILE"

  cd "$PROJECT_DIR"

  if [[ "$AUTO_PUSH" != "1" ]]; then
    log "Mode: DRY-RUN (report only). Set AIDS_AUTO_PUSH=1 to enable auto-push."
    log "Would run: $LEGION_CMD --prompt-file $PROMPT_FILE"
    log "Iteration prompt available at: $PROMPT_FILE"
  else
    log "Mode: AUTO-PUSH enabled."
    log "Running: $LEGION_CMD --prompt-file $PROMPT_FILE"
    $LEGION_CMD --prompt-file "$PROMPT_FILE" 2>&1 | tee -a "$LOG_DIR/iterate-${TIMESTAMP}.log"
  fi

  log "Iteration complete."

  # Cleanup old logs (keep last 7 days)
  find "$LOG_DIR" -name 'iterate-context-*.json' -mtime +7 -delete 2>/dev/null || true
  find "$LOG_DIR" -name 'iterate-*.log' -mtime +7 -delete 2>/dev/null || true
}

main "$@"
