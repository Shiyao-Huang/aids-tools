# Legion5 Code Review

**Reviewer:** Legion5 Codex Reviewer (agent-e2f77c963be6f528)
**Date:** 2026-05-18
**Branch:** main
**Commits reviewed:** `d83adf2..fa27671` + uncommitted working tree changes

---

## 变更总览

Legion5 迭代包含 6 个功能区域，涉及 4 个文件，共 +854/-39 行。

### 涉及文件

| 文件 | 变更类型 | 行数 |
|------|---------|------|
| `bin/selftools` | 功能增强 + 重构 | +264/-39 |
| `tests/test_selftools.py` | 新增测试 | +442 |
| `docs/architecture.md` | 文档更新 | +118 |
| `README_EN.md` | 新增文件 | +69 |

### 功能区域

1. **身份披露 enrichment** — identity_lines(), PostToolUse/SessionStart 增强
2. **FileLock TTL 重构** — 统一 acquire 路径 + TTL 过期
3. **stats --by-agent** — agent_id 聚合统计
4. **aids impact session analysis** — 文件影响面新增 agent 维度
5. **commit-stamp 增强** — JSON 输出 + trace summary
6. **doctor --clean-locks** — 智能锁清理
7. **测试覆盖** — 26 个新测试 (infer_runtime/actor_type, agent_id backfill, stats aggregation)

---

## P0: FileLock TTL 回归 — BLOCK MERGE

**严重程度：P0 — 阻塞合并**
**位置：** `bin/selftools` FileLock 类 (line 319-353)

### 问题描述

`_break_stale_lock()` 新增了 TTL 过期逻辑（30s），但该逻辑在**每次 `acquire()` 调用**时无条件执行：

```python
def _break_stale_lock(self) -> bool:
    # ...
    if age_ms > self.ttl * 1000:       # TTL=30s
        self.path.unlink()              # 无条件删除锁
        return True
```

`acquire()` 统一为 retry 循环（合并了 fcntl 和 rename 路径），每次循环都调用 `_break_stale_lock()`：

```python
def acquire(self):
    while True:
        self._break_stale_lock()    # ← 每次重试都执行 TTL 检查
        self._clean_stale_mtime()
        if self._try_acquire_nb():
            return self
```

### 影响

1. **长时间操作会被打断** — 任何持有锁 >30s 的操作（大文件写入、batch trace 写入）会被后续 acquire 无条件抢锁
2. **`--clean-locks` flag 失效** — TTL 清理已经自动发生，flag 变得无意义
3. **数据完整性风险** — 并发写入时锁被提前释放可能导致 JSONL 文件损坏
4. **QA 回归** — 2 个测试失败（`test_doctor_clean_locks_removes_stale`、`test_doctor_without_clean_locks_no_deletion`）

### 修复建议

将 TTL 过期检查从 `_break_stale_lock()` 分离为独立方法，仅在显式清理路径调用：

```python
def _break_stale_lock(self) -> bool:
    """仅检查 PID 是否存活"""
    # ... 保持原有 PID-based 检查，移除 TTL 逻辑

def _break_expired_lock(self) -> bool:
    """TTL 过期清理 — 仅在 --clean-locks 或显式 cleanup 中调用"""
    # ... TTL 检查逻辑放这里
```

或提高默认 TTL 到 300s（与 STALE_SECONDS 一致），避免正常操作被误杀。

---

## P1: 已确认（QA 报告）

### 1. CSV export 列头重复
- CSV 输出中列名重复 200+ 次
- 根因待确认（可能是 CSV writer 配置问题）
- **建议：** 修复后再合并

### 2. verify chain broken (8-9 条)
- 并发写入同一 jsonl 文件时 chain_hash 无法正确链接
- 文件锁保护了数据完整性但未保护 chain 连续性
- **建议：** 后续迭代修复，非阻塞

---

## 逐功能 Review

### 1. 身份披露 enrichment — APPROVE

**结论：安全、正确、可维护**

- `identity_lines()` 级联 fallback 正确
- PostToolUse/SessionStart 消息增强是纯追加，不破坏现有格式
- `_compact_trace()` 新字段遵循已有模式

**Minor 建议：**
- `cmd_hook_session_start()` 内联字段提取与 `identity_lines()` 重复（DRY）
- 缺少 `identity_lines({})` 空字典边界测试

### 2. FileLock TTL 重构 — P0 BLOCK（见上）

**架构改进肯定：**
- 统一 fcntl/rename 为单一代码路径 — 好的重构
- `_try_acquire_nb()` 正确委托到平台适配方法
- `_is_lock_expired()` 作为独立查询方法 — 设计合理

**问题在于 TTL 检查位置不对。**

### 3. stats --by-agent — APPROVE

- `sess_by_agent` / `trace_by_agent` 聚合逻辑正确
- `compute_agent_id()` fallback 在 session 缺少 agent_id 时自动计算 — 鲁棒
- JSON 和人类可读两种输出格式都有覆盖
- 7 个新测试覆盖多 agent 聚合、by-runtime/by-role 分组

### 4. aids impact session analysis — APPROVE

- trace 获取限制从 10 提升到 50 — 合理（session 分析需要更多数据）
- `session_map` 去重逻辑正确（`if sid in session_map: continue`）
- `operation_counts` 聚合无误
- 人类可读输出新增 agent 维度 — 有价值
- JSON 输出包含 `session_impact` 和 `unique_sessions` — 结构合理

**Minor：** `session_map` 的 agent 信息依赖 `t.get("session")`，如果 trace 中没有嵌套 session 对象则 fallback 到 trace 自身字段。这是正确的防御性编码。

### 5. commit-stamp 增强 — APPROVE

- JSON 输出新增 trace summary（count, resources, chain status）
- 人类可读输出新增 `AIDS-Trace-Summary` 和 `AIDS-Last-Trace` git trailers
- 直接读取 today_file — 简单高效，无注入风险

**Minor：** `resources` 字段在 JSON 输出中限制为 10 个，但未说明截断原因。建议加 `"truncated": true` 标记。

### 6. doctor --clean-locks — APPROVE (with P0 fix)

- 智能 stale 检测：先检查 PID 存活，再检查 mtime > STALE_SECONDS — 正确
- `--clean-locks` 添加 `clean_locks` check 到 doctor 输出 — 合理
- 错误处理完善（try/except OSError）

**注意：** P0 修复后此功能才能正常工作。

### 7. 测试覆盖 — GOOD

**26 个新测试，覆盖：**

| 测试类 | 数量 | 质量 |
|--------|------|------|
| TestInferRuntime | 7 | 全面（env 优先级、transcript 推断、edge cases） |
| TestInferActorType | 6 | 覆盖所有 runtime/actor 组合 |
| TestAgentIdBackfill | 5 | 新建/重注册/legacy 回填/跨 session 稳定性/唯一性 |
| TestStatsAgentAggregation | 7 | 多 agent 场景、by-runtime/role、unknown、resources |
| TestIdentityDisclosure | 2 | 基本字段断言 |
| TestRegisterSessionRuntimeBackfill | 1 | unknown runtime 保留旧值 |

**测试质量亮点：**
- `TestInferRuntime._clear_runtime_env()` 清理 helper 避免测试间干扰
- `TestAgentIdBackfill.test_different_agents_different_ids()` 验证唯一性约束
- `TestStatsAgentAggregation._seed_multi_agent()` 构建完整多 agent 场景

**测试覆盖缺口：**
- `identity_lines({})` 空字典边界
- `cmd_impact` session_impact 输出
- `cmd_commit_stamp` JSON 输出
- CSV export（已由 QA 确认为 P1 bug）

---

## 安全性总评

| 检查项 | 结果 |
|--------|------|
| 命令注入 | PASS — 无外部输入拼接到 shell 命令 |
| 路径遍历 | PASS — `_validate_path()` 仍保护锁路径 |
| JSON 注入 | PASS — 所有 JSON 输出通过 `json_dump()` |
| 竞态条件 | **WARN** — FileLock TTL 过早释放可能引入新竞态 |
| 信息泄露 | PASS — agent_id/session_id 是内部标识符，非敏感数据 |

---

## 总评

| 区域 | 评级 |
|------|------|
| 身份披露 | APPROVE |
| stats --by-agent | APPROVE |
| aids impact | APPROVE |
| commit-stamp | APPROVE |
| doctor --clean-locks | APPROVE (需 P0 fix 后) |
| FileLock TTL | **P0 BLOCK** — TTL 逻辑位置错误 |
| 测试覆盖 | GOOD (26 新测试) |
| 文档更新 | GOOD |

### 合并条件

1. **必须修复 FileLock TTL P0** — 将 TTL 检查从正常 acquire 路径分离
2. **建议修复 CSV export P1** — 列头重复
3. chain broken P1 可作为后续迭代

### install.sh 额外发现

`configure_codex_mcp()` 的 regex 只匹配 `BEGIN/END` 标记块，无法清理无标记的旧 `[mcp_servers.aids]` 块。重复运行 installer 会产生 duplicate key（用户已报告 `config.toml:64:14: duplicate key`）。建议 installer 增加无标记块的 fallback 匹配。
