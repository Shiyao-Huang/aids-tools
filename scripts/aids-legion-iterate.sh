#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AIDS Legion Self-Iteration — 每2h启动 5 Claude + 5 Codex 迭代
#
# 用法:
#   ./scripts/aids-legion-iterate.sh
#
# 定时 (cron):
#   0 */2 * * * cd ~/Desktop/selftools && ./scripts/aids-legion-iterate.sh >> ~/.aids/logs/legion.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AIDS_HOME="${AIDS_HOME:-$HOME/.aids}"
LOG_DIR="$AIDS_HOME/logs"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H%M%SZ")

# ── Logging ──────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [aids-legion] $*"; }

# ── Pre-flight ───────────────────────────────────────────────────────────────
if ! command -v npx &>/dev/null; then
  log "ERROR: npx not found. Install Node.js first."
  exit 1
fi

cd "$PROJECT_DIR"

# ── Gather context ───────────────────────────────────────────────────────────
trace_count=0
if [[ -d "$AIDS_HOME/traces" ]]; then
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    trace_count=$((trace_count + $(wc -l < "$f" | tr -d ' ')))
  done < <(find "$AIDS_HOME/traces" -name '*.jsonl' -mtime -1 2>/dev/null)
fi

rating_count=0
if [[ -d "$AIDS_HOME/ratings" ]]; then
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    rating_count=$((rating_count + $(wc -l < "$f" | tr -d ' ')))
  done < <(find "$AIDS_HOME/ratings" -name '*.jsonl' -mtime -1 2>/dev/null)
fi

active_sessions=0
if [[ -d "$AIDS_HOME/sessions" ]]; then
  active_sessions=$(grep -rl '"status": "active"' "$AIDS_HOME/sessions/" 2>/dev/null | wc -l | tr -d ' ')
fi

git_changes=0
if git rev-parse --git-dir &>/dev/null; then
  git_changes=$(git log --oneline HEAD~10..HEAD 2>/dev/null | wc -l | tr -d ' ')
fi

# ── Build iteration prompt ───────────────────────────────────────────────────
PROMPT_FILE="$PROJECT_DIR/.aha/prompts/aids-iteration.md"
mkdir -p "$(dirname "$PROMPT_FILE")"

cat > "$PROMPT_FILE" <<'PROMPT_EOF'
# AIDS Self-Iteration Prompt

## 上下文
你是 AIDS (Agent-ID System) 迭代团队。项目是一个零依赖的 agent 身份感知+trace+rating 系统。

仓库: https://github.com/Shiyao-Huang/aids-tools
目录: /Users/copizzah/Desktop/selftools

## 迭代目标
每次迭代按优先级执行：

### P0: Bug 修复 + 测试
1. `npm test` 通过
2. `aids doctor` 全绿
3. 测试 `aids who-touched`、`aids rate`、`aids op-chain` 功能

### P1: 功能增强
1. 改进 `who-touched` 输出格式（颜色+排序）
2. 添加 `aids timeline` 命令
3. 改进 Bash 文件变更解析
4. 添加 `aids stats` 统计命令

### P2: 文档 + Demo
1. 用真实命令输出替换 README 占位符
2. 添加英文版 README

### P3: 架构改进
1. 改进并发锁机制
2. 添加 `aids export` 导出命令
3. 优化 timeline JSONL 写入性能

## 规则
- 零依赖原则
- `npm test` 必须 PASS
- commit 前跑 `aids doctor`
- 中文沟通
- 完成后 commit + push GitHub

## 团队: 5 Claude + 5 Codex
- Claude: implementer ×2 + architect + qa + scribe
- Codex: implementer ×2 + researcher + reviewer + qa

## 实时数据
PROMPT_EOF

cat >> "$PROMPT_FILE" <<EOF
- 最近24h traces: ${trace_count}
- 最近24h ratings: ${rating_count}
- 活跃 sessions: ${active_sessions}
- 最近 git commits: ${git_changes}
- 迭代时间: ${TIMESTAMP}
EOF

# ── Launch Legion ────────────────────────────────────────────────────────────
log "Starting AIDS legion iteration at ${TIMESTAMP}"
log "Context: traces=${trace_count} ratings=${rating_count} sessions=${active_sessions} commits=${git_changes}"
log "Team: 5 Claude + 5 Codex"
log "Prompt: ${PROMPT_FILE}"

export AIDS_SESSION_ID="legion-${TIMESTAMP}"
export AIDS_RUNTIME="bash"
export AIDS_ROLE="orchestrator"
export AIDS_INTENT="定时迭代"

npx aha legion \
  --cwd "$PROJECT_DIR" \
  2>&1 | tee -a "$LOG_DIR/legion-${TIMESTAMP}.log"

log "Legion iteration complete."

# Cleanup old logs (7 day retention)
find "$LOG_DIR" -name 'legion-*.log' -mtime +7 -delete 2>/dev/null || true
