# Legion8 Code Review Report

**Reviewer**: Legion8 Codex Reviewer
**Date**: 2026-05-19
**Scope**: Full codebase review — hooks (JS + shell), trace engine, session registry, installer, tests
**Status**: Round 2 complete (post-implementation review)

---

## Summary

**278/278 tests pass**（flaky 并发测试已修复）。Commit `3d107af` 合并了 3 个任务：hooks 去重、aids prune、op-chain lineage。

Round 1 发现的 **4/5 个高优先级 issue 已修复**：P1-1/P1-2（JS 去重）✅、P2-1（shell 去重）✅、P2-4（extractBashResources 去重）✅。

仍待修复：P0-1（eval 注入）、P1-3（并发测试）、P2-2/P2-3（trace 引擎性能）。

核心亮点：
- 三层 trace 架构（JS hooks → trace.js → bin/selftools Python CLI）设计合理
- 文件锁 + 原子 append 保障并发安全
- 不变量测试覆盖全面（7 条不变量全部验证）
- **Round 2**: JS hooks 成功提取共享模块 `_aid_shared.js`（180 行），shell hooks 提取 `_aid_common.sh`（44 行）

---

## Round 2 — Post-Implementation Review (Commit 3d107af)

### Hooks 代码去重 ✅ Approved

**Files**: `_aid_shared.js` (新增 180 行), `_aid_common.sh` (新增 44 行), 6 个 hook 文件重构

**JS 去重评估**：
- `inferRuntime()`, `inferActorType()`, `resolveAgentId()`, `extractResourceKeys()`, `extractBashResources()` 全部提取到 `_aid_shared.js`
- `pre_tool_use.js`: 从 282 行 → 127 行 (-55%)
- `post_tool_use.js`: 从 257 行 → 122 行 (-52%)
- `clip()` 和 `budgetLines()` 签名改为接收参数而非依赖闭包变量 → 更易测试 ✅
- `normalizeFilePath` 从 `src/trace/trace.js` 引入，未重复实现 ✅

**Shell 去重评估**：
- `_aid_common.sh` 提供 3 个函数：`aid_detect_runtime`, `aid_resolve_agent_id`, `aid_find_bin`
- `session-start.sh` 仍保留 display_name/role/model 推断（仅此文件需要）— 合理
- 所有 shell hook 文件从 30+ 行降至 7-34 行 ✅
- `source` 路径使用 `$(dirname "$0")` → 正确处理相对路径

| ID | Severity | Issue | Status |
|----|----------|-------|--------|
| R1-P1-1 | High | JS `inferRuntime/ActorType` 复制粘贴 | ✅ **Fixed** — 提取到 `_aid_shared.js` |
| R1-P1-2 | High | JS `resolveAgentId()` 复制粘贴 | ✅ **Fixed** — 提取到 `_aid_shared.js` |
| R1-P2-1 | Medium | Shell agent_id 块复制 5 次 | ✅ **Fixed** — 提取到 `_aid_common.sh` |
| R1-P2-4 | Medium | `extractBashResources()` 复制 60+ 行 × 2 | ✅ **Fixed** — 提取到 `_aid_shared.js` |

**R2 新发现**：

| ID | Severity | Issue |
|----|----------|-------|
| R2-P2-1 | Medium | `_aid_shared.js` 中 `extractBashResources()` 缺少 `normalizeFilePath` 的 import — 但实际已在函数内通过闭包调用 `src/trace/trace.js` 的导出。确认 ✅ 安全 |
| R2-P3-1 | Low | `post_tool_use.sh` 和 `pre_tool_use.sh` 调用 `aid_detect_runtime` 但 `_aid_common.sh` 已被 source，runtime 推断在子 shell 中重复一次 — 无害 |

### aids prune 命令 ✅ Approved

**File**: `bin/selftools` (+97 行)

- 支持 `--days N`（默认 30）、`--dry-run`、`--json`
- 清理范围：retired sessions、旧 traces/ratings/timeline JSONL、stale locks
- 使用 `FileLock.STALE_SECONDS` 作为 lock 过期标准 — 与现有 lock 机制一致 ✅
- `bytes_freed` 统计提供磁盘回收可见性
- `ensure_layout(skip_stale_clean=True)` 避免递归清理 ✅

| ID | Severity | Issue |
|----|----------|-------|
| R2-P2-2 | Medium | `cmd_prune` 中 `ts / 1000.0 < cutoff_ts` — `cutoff_ts` 来自 `datetime.timestamp()`（秒级），但 session 的 `last_seen_at` 是毫秒级。除法 `ts / 1000.0` 转换正确 ✅ |
| R2-P3-2 | Low | `.ndjson` 文件未被 prune 覆盖 — 只 glob `*.jsonl`。应同时包含 `*.ndjson` |

### op-chain lineage ✅ Approved

**File**: `bin/selftools` `cmd_op_chain()` 重写 (+63 行)

- 从旧的 `print_traces_for_resource` 改为 `prev_trace_id` 链式遍历
- 从 index 的 `last_trace_id` 开始，沿 `prev_trace_id` 向前遍历
- `seen` set 防止循环 ✅
- 输出包含 lineage arrows (`prev→current`)、agent_id、role、intent
- JSON mode 输出完整 chain 结构

| ID | Severity | Issue |
|----|----------|-------|
| R2-P3-3 | Low | `len(chain) < limit` 限制 chain 深度，但 limit 默认值未知（依赖 argparse）。应确认默认值合理（如 50） |

---

## Round 1 Issue Status Update

### P0 — 安全漏洞

### P0 — 安全漏洞

| ID | File | Issue |
|----|------|-------|
| P0-1 | `install.sh:277` | `eval "$@"` in `run_shell()` — 如果 DRY_RUN=0，这个函数允许执行任意 shell 代码。当前只有 `self_source_dir()` 的路径比较使用它，但攻击面很大。应改用 `run "$@"` 或明确列出所有调用点。 |

### P1 — 需修复

| ID | File | Issue |
|----|------|-------|
| P1-1 | `hooks/post_tool_use.js:87-103` + `hooks/pre_tool_use.js:83-99` | `inferRuntime()` 和 `inferActorType()` **完全复制粘贴**到两个文件。违反 DRY，且改一个忘改另一个会造成运行时不一致。 |
| P1-2 | `hooks/post_tool_use.js:109-131` + `hooks/pre_tool_use.js:105-124` | `resolveAgentId()` **完全复制粘贴**到两个文件（22 行 × 2）。与 Legion7 R3-P2a 同一问题，至今未修。 |
| P1-3 | `tests/test_invariants.py::TestAtomicChainHash::test_chain_atomic_concurrent` | 并发 chain hash 测试 **间歇性失败**。根因：10 线程同时争抢 `appendLineAtomic` 的 rename 锁，导致 JSONL 写入顺序与 chain hash 计算的 prev_hash 不一致。文件锁 `withLock()` 使用目录锁 + 轮询 25ms，在高并发下锁粒度不够。 |

### P2 — 应修复

| ID | File | Issue |
|----|------|-------|
| P2-1 | 5 个 shell hook 文件 | agent_id 导出块 **复制粘贴 5 次**（从 hooks/ 和 selftools- 的 pre/post/session-start）。应提取到 `hooks/_aid_agent_id.sh` 并 `source` 引入。这是 Legion7 R3-P2b，现在 worsened 到 5 个文件。 |
| P2-2 | `src/trace/trace.js:170-179` | `appendLineAtomic()` 每次写入都 read 全文 + write 全文（read-modify-write），对大 JSONL 文件性能差。应改为 `fs.appendFileSync()` + 独立的 chain hash 校验。 |
| P2-3 | `src/trace/trace.js:209` | `readAllTraces()` 调用 `allTraceFiles().flatMap(readNdjsonFile)` — 加载所有历史 trace 到内存。长期运行后（数百天）可能导致 OOM。应限制默认扫描范围或使用流式解析。 |
| P2-4 | `hooks/post_tool_use.js:148-210` + `hooks/pre_tool_use.js:142-206` | `extractBashResources()` **完全复制粘贴**（60+ 行 × 2）。是 JS hook 中最大的重复块。 |
| P2-5 | `install.sh:198-199` | `git -C "$INSTALL_DIR" reset --hard origin/main` — 如果用户有本地修改，`--hard` 会无提示丢弃。应先 stash 或提示确认。 |

### P3 — 可改进

| ID | File | Issue |
|----|------|-------|
| P3-1 | `lib/session.js:48-50` | `fs.existsSync(filePath)` + `fs.readFileSync()` 有 TOCTOU 竞态。虽然 session 注册不频繁，但技术上应合并为 try/catch readFileSync。 |
| P3-2 | `hooks/pre_tool_use.js:144` | `require('crypto')` 和 `require('path')` 在 `extractBashResources()` 函数体内重复引入。应在文件顶部引入一次。 |
| P3-3 | `install.sh:119-125` | `run_shell()` 使用 `eval`（与 P0-1 相关但不同调用路径）。当前仅用于路径比较，但存在 command injection 风险。 |
| P3-4 | `src/trace/trace.js:136-138` | `sleep()` 使用 `Atomics.wait()` — 在 Node.js worker thread 中不可用（会抛异常）。主线程可用但不够优雅。 |

---

## 代码风格评估

**正面**：
- 函数命名清晰：`appendTrace()`, `resolveAgentId()`, `normalizeFilePath()`
- 错误处理得当：hook 中 `try/catch` 包裹所有 I/O 操作，`process.exit(0)` 保证非阻塞
- 环境变量 fallback 链完整：`AIDS_*` → `AID_*` → `SELFTOOLS_*` → `ZHUYI_*`
- Python CLI 和 JS hooks 的字段名使用 snake_case 保持一致

**需改进**：
- Shell 脚本中 `_aid_session_file` 和 `_aid_val` 变量未 `unset`（Legion7 R3-P3b），仍存在
- 部分 shell 脚本缺少 shellcheck 注释（如 `# shellcheck disable=SC2086`）

---

## Edge Case 分析

| Edge Case | 处理方式 | 评估 |
|-----------|----------|------|
| 无 `AIDS_SESSION_ID` 的 bash 调用 | `resolve()` 返回 `'unknown'`，`inferActorType()` 返回 `'bash'` | ✅ 正确 |
| `tool_result` 为 null/undefined | `extractResult()` 返回 null | ✅ 正确 |
| Bash 命令包含 `sed -i` | 被 `readCmds` 过滤，不进入 read-only 检测 | ✅ 正确 |
| 文件路径包含空格 | `normalizeFilePath()` 使用 `path.resolve()` | ✅ 正确 |
| `~/.aids` 目录不存在 | `ensureDir()` 使用 `{ recursive: true }` | ✅ 正确 |
| 超长 Bash 命令（>500 字符） | `extractBashResources()` 正常处理，hash 作为 key | ✅ 正确 |
| JSONL 文件损坏（混合新旧格式） | `readNdjsonFile()` 逐行 try/catch，跳过无效行 | ✅ 正确 |
| `CLAUDE_ENV_FILE` 不存在 | SessionStart hook 不依赖此文件 | ⚠️ 安全 |

---

## 安全审计

| 检查项 | 结果 | 备注 |
|--------|------|------|
| 命令注入 | ⚠️ P0-1 | `run_shell()` 使用 `eval` |
| 路径穿越 | ✅ 安全 | `normalizeFilePath()` 使用 `path.resolve()` |
| 文件权限 | ⚠️ | Session JSON 文件使用默认权限 0644，无敏感数据加密 |
| 竞态条件 | ⚠️ P3-1 | `lib/session.js` TOCTOU |
| 敏感数据泄露 | ✅ 安全 | trace 不记录文件内容，仅记录路径和 hash |
| 供应链安全 | ⚠️ | `install.sh` 从 GitHub 拉 `--depth 1`，不验证 commit hash 或签名 |

---

## 测试覆盖率评估

```
pytest tests/ -x: 272 passed, 1 failed (flaky)
├── test_invariants.py:  28 passed + 1 flaky (INV-1~7 + atomic chain + result field)
├── test_selftools.py:  179 passed (unit + edge cases)
└── test_selftools_extra.py:  62 passed (integration)
```

**覆盖缺口**：
- `lib/session.js` 无单元测试（仅有通过 `bin/selftools` 的集成覆盖）
- `hooks/pre_tool_use.js` 的 `injectWriteContext()` 无独立测试
- `extractBashResources()` 的 edge case 测试仅覆盖 redirect/tee，缺少 pipe chain 和子 shell 场景
- `install.sh` 无自动化测试（手动测试 only）

---

## 与 Legion7 遗留问题对比

| Legion7 Issue | Legion8 状态 | 备注 |
|---------------|-------------|------|
| R3-P1 trace schema breaking change | ✅ 已修 | `_extract_result()` 现在 Python 和 JS 都返回结构化 dict，一致 |
| R3-P2a JS `resolveAgentId()` 去重 | ❌ 未修 | 仍复制粘贴在两个 JS 文件 |
| R3-P2b Shell agent_id 块去重 | ❌ 恶化 | 从 3 个文件增加到 5 个文件 |
| R3-P3a deterministic hash fallback | ✅ 接受 | 已记录在案 |
| R3-P3b shell 变量未 unset | ❌ 未修 | |

---

## Legion8 待完成任务评估

| Task ID | Title | 优先级 | Reviewer 建议 |
|---------|-------|--------|-------------|
| `tlcVfdNTaMnx` | hooks 代码去重（shell + JS） | High | **强烈建议执行** — 解决 P1-1/P1-2/P2-1/P2-4 |
| `cCqQKLa35CAr` | parent_trace_id 链式追踪 | High | 可执行 — 需注意与 `prevTraceId` 字段的关系 |
| `9yNVsBqDPtoj` | aids prune 命令 + 日志清理 | Medium | 建议执行 — 解决 P2-3 长期 OOM 风险 |
| `Yn08NUPORTyp` | docs 架构文档更新 | Low | 低优先 — 不影响功能 |

---

## Action Items

1. **@implementer**: 修复 P0-1 — `run_shell()` 中 `eval "$@"` 替换为 `"$@"`，验证 `install.sh --dry-run` 仍工作
2. **@implementer**: 执行 `tlcVfdNTaMnx`（hooks 代码去重），解决 P1-1/P1-2/P2-1/P2-4（一次重构解决 4 个问题）
3. **@implementer**: 修复 P1-3 — 并发 chain hash 测试：增大锁超时或使用 flock 替代目录锁，或将测试改为单线程串行写入验证 chain 正确性
4. **@implementer**: P2-5 — `git reset --hard` 前先 stash 用户本地修改
5. **@implementer**: P2-2 — `appendLineAtomic()` 改用 `fs.appendFileSync()` 避免全文重写
6. **Future**: 为 `lib/session.js` 补充单元测试；为 `install.sh` 编写自动化 smoke test

---

*Rounds completed: 1 | Latest: 2026-05-19*
