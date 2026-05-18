# Legion7 Code Review Report

**Reviewer**: Legion7 Codex Reviewer (agent-3ac0263278d644b8)
**Date**: 2026-05-18
**Scope**: Commits fc3db72 → 7b40825 + uncommitted _extract_result()
**Status**: Round 3 complete

---

## Summary

4 commits since Round 1. 3/5 Legion7 tasks committed, 1 in progress (PostToolUse result). 270/270 tests pass. P1 FileLock TTL **fixed**. P2 hooks code duplication **still open** (now 5 files). New: `_extract_result()` 是 trace schema breaking change。

---

## Commit History Reviewed

| Commit | Description | Verdict |
|--------|-------------|---------|
| `fc3db72` | Atomic chain hash write + check_ttl wiring | ✅ P1 fixed, tests pass |
| `82028fd` | FileLock TTL acquire-skip + clean-locks tests | ✅ Clean |
| `7b40825` | agent_id propagation across all hooks (47%→100%) | ⚠️ See R3 findings |

---

## Round 3 — Committed: 7b40825 (agent_id hooks)

**Files**: 7 hook files, +125/-5

**JS hooks** (`pre_tool_use.js`, `post_tool_use.js`):
- `resolveAgentId()` 3-tier fallback: env var → session file → deterministic hash
- `agent_id` now passed to `appendTrace()` and shown in stderr output
- Error handling with try/catch around file reads ✅

**Shell hooks** (5 `.sh` files):
- Same agent_id export block using grep+sed JSON parsing

| ID | Severity | Issue | Status |
|----|----------|-------|--------|
| R3-P2a | Medium | `resolveAgentId()` 复制粘贴到 `pre_tool_use.js` 和 `post_tool_use.js`（22 行 × 2） | Open — 应提取到 `lib/agent_id.js` |
| R3-P2b | Medium | agent_id shell 导出块复制粘贴到 5 个文件（从 Round 2 的 3 个增加到 5 个） | **Worsened** — 应提取到 `hooks/_aid_agent_id.sh` |
| R3-P3a | Low | Deterministic hash fallback 用 `display_name:role:team_id`，role 变更会改变 agent_id | Accepted — 记录在案 |
| R3-P3b | Low | Shell 变量 `_aid_session_file`/`_aid_val` 未 unset | Open |

---

## Round 3 — Uncommitted: `_extract_result()` (PostToolUse task)

**Task**: `JXREVQTbEXfX` — PostToolUse result 字段捕获
**File**: `bin/selftools` (+33 lines)

**What changed**:
- `result` 字段从 `short(event.get("tool_result"), 500)` (string) 改为 `_extract_result(event)` (dict)
- 新函数返回 `{"status": "success"/"error", "exit_code": N, "preview": "..."}`
- 检测 `is_error` flag + content pattern (`"error:"`, `"permission denied"`)
- 从 Bash 输出解析 `Exit code: N`

**⚠️ R3-P1: Trace Schema Breaking Change**

```python
# Before (string):
"result": short(event.get("tool_result"), 500)

# After (dict):
"result": {"status": "success", "exit_code": 0, "preview": "..."}
```

- 所有下游读取 `trace["result"]` 并期望 string 的代码会 break
- `_append_trace_chain_atomic()` 将 `result` 计入 chain hash，值的变化会导致 hash 不连续
- `aids export --format csv` 列头会从 `result:text` 变为嵌套结构
- **建议**: 提交前运行 `aids export --format csv` 验证列结构，或在新字段名下添加 dict（如 `result_meta`），保持 `result` 为 string 兼容

**其他 findings**:

| ID | Severity | Issue |
|----|----------|-------|
| R3-P3c | Low | `"permission denied"` 仅匹配英文 — 多语言环境可能遗漏 |
| R3-P3d | Low | `short(raw_str, 300)` 在 preview 中折叠空白，可能丢失格式信息 |

---

## Task Board — Review Status

| Task ID | Title | Commit | Review |
|---------|-------|--------|--------|
| `0jNjjy7bSo9v` | FileLock TTL acquire 路径跳过 | fc3db72 + 82028fd | ✅ **Approved** |
| `DFAenBIaSWPO` | 原子 chain hash 写入 | fc3db72 | ✅ **Approved** (P2 open, accepted) |
| `0rrUZSmweLpw` | agent_id 注入覆盖率提升 | 7b40825 | ✅ **Approved** (P2 duplication noted) |
| `JXREVQTbEXfX` | PostToolUse result 字段捕获 | Uncommitted | ⚠️ **P1 schema break — 需修复后 re-review** |
| `Yn08NUPORTyp` | docs 架构文档更新 | Todo | — |

---

## Test Evidence

```
pytest tests/ -x: 270 passed in 12.69s
├── test_hook_output_contract.py: 1 passed
├── test_invariants.py: 28 passed (含并发 chain hash 测试)
├── test_selftools.py: 179 passed (含 FileLock TTL acquire-skip)
└── test_selftools_extra.py: 62 passed
```

---

## Action Items (Updated Round 3)

1. ~~P1 check_ttl wiring~~ **DONE** ✅
2. **@implementer (PostToolUse task)**: `_extract_result()` 返回 dict 导致 trace schema breaking change。建议: 用 `result_meta` 新字段存 dict，保持 `result` 为 string 向后兼容。提交前验证 `aids export --format csv` 输出。
3. **@implementer (agent_id task)**: 5 个 shell hook 的 agent_id 块应提取为 `hooks/_aid_agent_id.sh` 并 source 引入
4. **@implementer (agent_id task)**: 2 个 JS hook 的 `resolveAgentId()` 应提取到 `lib/agent_id.js`
5. **Future**: 补充 acquire 路径端到端集成测试

---

*Rounds completed: 3 | Latest: 2026-05-18 23:10*
*Session: 47afab1-306d-499a-b7a6-b7942560f9f8*
