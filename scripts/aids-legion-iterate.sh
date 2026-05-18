#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AIDS Legion Self-Iteration — 2h 定时 5 Claude + 5 Codex
#
# 用法:
#   ./scripts/aids-legion-iterate.sh
#   ./scripts/aids-legion-iterate.sh --dry-run
#
# 定时 (cron):
#   17 */2 * * * cd ~/Desktop/selftools && ./scripts/aids-legion-iterate.sh >> ~/.aids/logs/legion.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AIDS_HOME="${AIDS_HOME:-$HOME/.aids}"
LOG_DIR="$AIDS_HOME/logs"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
TEAM_NAME="aids-iterate-${TIMESTAMP}"
DRY_RUN=0

# ── Flags ────────────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

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

git_log=""
if git rev-parse --git-dir &>/dev/null; then
  git_log=$(git log --oneline HEAD~5..HEAD 2>/dev/null || echo "no recent commits")
else
  git_log="not a git repo"
fi

git_diff_summary=""
if git rev-parse --git-dir &>/dev/null; then
  git_diff_summary=$(git diff --stat HEAD 2>/dev/null || echo "clean")
fi

# ── Build iteration prompt ───────────────────────────────────────────────────
PROMPT_FILE="$PROJECT_DIR/.aha/prompts/aids-iteration.md"
mkdir -p "$(dirname "$PROMPT_FILE")"

cat > "$PROMPT_FILE" <<'PROMPT_HEAD'
# AIDS Self-Iteration Prompt

## 上下文
你是 AIDS (Agent-ID System) 迭代团队。项目是一个零依赖的 agent 身份感知+trace+rating 系统。

仓库: https://github.com/Shiyao-Huang/aids-tools
目录: /Users/copizzah/Desktop/selftools

## 迭代目标 (按优先级)

### P0: Bug 修复 + 测试
1. `npm test` 必须通过 (如有)
2. `aids doctor` 全绿
3. 测试 `aids who-touched`、`aids rate`、`aids op-chain` 功能
4. 修复 install.sh 中 ensure_gitnexus 缺失等问题

### P1: 功能增强
1. 改进 `who-touched` 输出格式（颜色+排序）
2. 添加 `aids timeline` 命令（如果尚未完成）
3. 改进 Bash 文件变更解析
4. 添加 `aids stats` 统计命令
5. 确保 MCP tools 正常工作 (aids_doctor, aids_who_touched, aids_rate, etc.)

### P2: 文档 + Demo
1. 用真实命令输出替换 README 占位符
2. 添加英文版 README

### P3: 架构改进
1. 改进并发锁机制
2. 添加 `aids export` 导出命令
3. 优化 timeline JSONL 写入性能

## GitNexus 集成
GitNexus 已安装在 /Users/copizzah/.local/bin/gitnexus (v1.6.5)。
selftools repo 已索引 (692 nodes, 1156 edges, 26 clusters)。
可用 `gitnexus query <file>` 查询代码图谱。
在 `aids who-touched` 等命令中可附加 GitNexus context。

## 规则
- 零依赖原则 — 只用 Node.js 和 Python 3 标准库
- 测试必须 PASS
- commit 前跑 `aids doctor`
- 中文沟通
- 完成后 commit + push GitHub (如果 AIDS_AUTO_PUSH=1)

## 团队分工: 5 Claude + 5 Codex
### Claude agents (4x implementer + 1x qa)
- Claude Impl #1: P0 bug 修复
- Claude Impl #2: P1 功能增强
- Claude Impl #3: P2 文档更新
- Claude Impl #4: P3 架构改进
- Claude QA: 验证所有 P0-P3 变更

### Codex agents (2x implementer + 1x researcher + 1x reviewer + 1x qa)
- Codex Impl #1: P0 bug 修复 (与 Claude #1 配合)
- Codex Impl #2: P1 功能增强 (与 Claude #2 配合)
- Codex Researcher: 分析 traces/ratings 数据, 提出改进建议
- Codex Reviewer: review 所有 PR/commits
- Codex QA: 独立验证 + 边缘测试

## 实时数据
PROMPT_HEAD

cat >> "$PROMPT_FILE" <<EOF
- 最近24h traces: ${trace_count}
- 最近24h ratings: ${rating_count}
- 活跃 sessions: ${active_sessions}
- 最近 git commits:
$(echo "$git_log" | sed 's/^/  /')
- Git diff stat:
$(echo "$git_diff_summary" | sed 's/^/  /')
- 迭代时间: ${TIMESTAMP}
EOF

# ── Agent spec templates ─────────────────────────────────────────────────────
SPECS_DIR="$PROJECT_DIR/.aha/specs/${TIMESTAMP}"
mkdir -p "$SPECS_DIR"

# Helper: write agent spec JSON
write_spec() {
  local file="$1" runtime="$2" role="$3" name="$4" goal="$5"
  cat > "$file" <<EOF
{
  "kind": "aha.agent.v1",
  "name": "${name}",
  "runtime": "${runtime}",
  "prompt": {
    "system": "你是 AIDS 迭代团队的 ${name}。参考 .aha/prompts/aids-iteration.md 迭代 prompt 执行任务。使用 list_tasks 查看可用任务，start_task 领取任务。完成后用 complete_task 标记。中文沟通。",
    "context": ["项目: AIDS Agent-ID System，零依赖 Python CLI"]
  },
  "tools": { "allow": ["*"] },
  "permissions": { "mode": "bypassPermissions" },
  "context": {
    "messaging": "中文沟通，完成后报告",
    "behavior": { "onIdle": "claim-task", "onComplete": "complete-task" }
  }
}
EOF
}

# Claude agents (5)
write_spec "$SPECS_DIR/claude-impl-1.json" claude implementer "Claude Impl #1" "P0 bug fixes"
write_spec "$SPECS_DIR/claude-impl-2.json" claude implementer "Claude Impl #2" "P1 feature enhancement"
write_spec "$SPECS_DIR/claude-impl-3.json" claude implementer "Claude Impl #3" "P2 docs update"
write_spec "$SPECS_DIR/claude-impl-4.json" claude implementer "Claude Impl #4" "P3 architecture"
write_spec "$SPECS_DIR/claude-qa.json"     claude qa-engineer "Claude QA" "Verify all changes"

# Codex agents (5)
write_spec "$SPECS_DIR/codex-impl-1.json"   codex implementer "Codex Impl #1" "P0 bug fixes"
write_spec "$SPECS_DIR/codex-impl-2.json"   codex implementer "Codex Impl #2" "P1 feature enhancement"
write_spec "$SPECS_DIR/codex-researcher.json" codex researcher "Codex Researcher" "Analyze traces/ratings"
write_spec "$SPECS_DIR/codex-reviewer.json"  codex reviewer "Codex Reviewer" "Review all changes"
write_spec "$SPECS_DIR/codex-qa.json"        codex qa-engineer "Codex QA" "Independent verification"

# ── Launch ───────────────────────────────────────────────────────────────────
log "Starting AIDS legion iteration at ${TIMESTAMP}"
log "Context: traces=${trace_count} ratings=${rating_count} sessions=${active_sessions}"
log "Team: 5 Claude + 5 Codex = 10 agents"
log "Prompt: ${PROMPT_FILE}"

export AIDS_SESSION_ID="legion-${TIMESTAMP}"
export AIDS_RUNTIME="bash"
export AIDS_ROLE="orchestrator"
export AIDS_INTENT="2h定时迭代"

if [ "$DRY_RUN" -eq 1 ]; then
  log "[DRY-RUN] Would create team: ${TEAM_NAME}"
  log "[DRY-RUN] Would spawn 10 agents from ${SPECS_DIR}"
  log "[DRY-RUN] Prompt written to ${PROMPT_FILE}"
  log "[DRY-RUN] Specs written:"
  ls -1 "$SPECS_DIR"/*.json | while read -r f; do
    log "[DRY-RUN]   $(basename "$f")"
  done
  exit 0
fi

# Step 1: Create team
log "Creating team: ${TEAM_NAME}"
TEAM_ID=$(npx aha teams create --name "$TEAM_NAME" --goal "AIDS self-iteration ${TIMESTAMP}" 2>&1 | grep -oE 'team_[a-zA-Z0-9]+' || echo "")

if [ -z "$TEAM_ID" ]; then
  # Fallback: use current team
  TEAM_ID="49ddc1b0-425f-4d0a-8ee5-f7c876fea811"
  log "Using existing team: ${TEAM_ID}"
else
  log "Created team: ${TEAM_ID}"
fi

# Step 2: Create iteration tasks on the board
log "Creating iteration tasks..."
TASK_P0=$(npx aha tasks add "P0: Bug fixes — doctor/rate/op-chain verification" \
  --team "$TEAM_ID" --priority urgent 2>&1 | grep -oE '[a-zA-Z0-9_-]{20,}' | head -1 || echo "")
TASK_P1=$(npx aha tasks add "P1: Feature enhancement — timeline/stats/who-touched" \
  --team "$TEAM_ID" --priority high 2>&1 | grep -oE '[a-zA-Z0-9_-]{20,}' | head -1 || echo "")
TASK_P2=$(npx aha tasks add "P2: Docs — README real output + English version" \
  --team "$TEAM_ID" --priority medium 2>&1 | grep -oE '[a-zA-Z0-9_-]{20,}' | head -1 || echo "")
TASK_P3=$(npx aha tasks add "P3: Architecture — locks/export/perf" \
  --team "$TEAM_ID" --priority low 2>&1 | grep -oE '[a-zA-Z0-9_-]{20,}' | head -1 || echo "")

# Step 3: Spawn 5 Claude agents
log "Spawning 5 Claude agents..."
for spec in claude-impl-1 claude-impl-2 claude-impl-3 claude-impl-4 claude-qa; do
  log "  Spawning ${spec}..."
  npx aha agents spawn "$SPECS_DIR/${spec}.json" \
    --team "$TEAM_ID" \
    --role "$(python3 -c "import json; print(json.load(open('$SPECS_DIR/${spec}.json'))['baseRoleId'])")" \
    --path "$PROJECT_DIR" \
    2>&1 | tail -1 || true
done

# Step 4: Spawn 5 Codex agents
log "Spawning 5 Codex agents..."
for spec in codex-impl-1 codex-impl-2 codex-researcher codex-reviewer codex-qa; do
  log "  Spawning ${spec}..."
  npx aha agents spawn "$SPECS_DIR/${spec}.json" \
    --team "$TEAM_ID" \
    --role "$(python3 -c "import json; print(json.load(open('$SPECS_DIR/${spec}.json'))['baseRoleId'])")" \
    --path "$PROJECT_DIR" \
    2>&1 | tail -1 || true
done

log "All 10 agents spawned. Iteration ${TIMESTAMP} running."
log "Monitor: npx aha team status ${TEAM_ID}"

# Step 5: Wait for completion (with timeout)
TIMEOUT=${ITERATION_TIMEOUT_MINUTES:-90}
log "Waiting up to ${TIMEOUT} minutes for iteration to complete..."
log "Team: ${TEAM_ID}"
log "Log: ${LOG_DIR}/legion-${TIMESTAMP}.log"

# Cleanup old logs (7 day retention)
find "$LOG_DIR" -name 'legion-*.log' -mtime +7 -delete 2>/dev/null || true
# Cleanup old specs (1 day retention)
find "$PROJECT_DIR/.aha/specs" -mindepth 1 -maxdepth 1 -type d -mtime +1 -exec rm -rf {} + 2>/dev/null || true

log "Iteration ${TIMESTAMP} launched successfully."
