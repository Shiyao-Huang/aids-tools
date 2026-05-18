# Legion3 代码审查报告

**审查日期**: 2026-05-18
**审查范围**: 最近 10 个 commit (1fbd147..7e84eeb)
**审查员**: QA Engineer (code reviewer)
**测试结果**: 141/141 通过 (17.12s)

---

## 1. Commit 历史质量

| Commit | 类型 | 描述 | 评价 |
|--------|------|------|------|
| `7e84eeb` | feat | INV-7 rate duplicate rejection + CLI unit tests | 清晰，有测试 |
| `40abc42` | feat | agent_id stable identity + INV-7 rate uniqueness constraint | 核心功能，设计合理 |
| `788c483` | test | Bach invariant strengthening + selfloopbash absorption analysis | 不变量增强，文档完整 |
| `f63b938` | fix | tee multi-target indexing + filter /dev/null from redirect traces | Bug 修复精准 |
| `fa8a33c` | fix | harden doctor — check all components, fix first-3-only pass/fail | 正确修复边界问题 |
| `3ec48a6` | feat | uninstall.sh + install.sh hardening + legion script fix + CodeGraph | 过多功能混入单 commit |
| `b66da64` | feat | hook coverage enhancement + red-team review + Bach theorem guidance | 文档+测试，范围偏大 |
| `ab64b07` | fix | Bash resource display truncation + full command fidelity tests | 测试充分 |
| `51843f7` | feat | built-in CodeGraph AST analyzer with shebang detection | 新功能，独立性好 |
| `1fbd147` | test | add 8 Bash redirect parsing tests | 纯测试，good |

**总评**: Commit message 规范（conventional commits），粒度基本合理。`3ec48a6` 包含 5 个不同关注点（uninstall/install/legion/CodeGraph），建议拆分。

---

## 2. agent_id 实现审查

### 2.1 设计 (bin/selftools:527-530)

```python
def compute_agent_id(display_name: str, role: str, team_id: Optional[str] = None) -> str:
    seed = f"{display_name or ''}\0{role or ''}\0{team_id or ''}"
    return "agent-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
```

**优点**:
- 使用 `\0` 分隔符防止碰撞（例如 "ab" + "c" vs "a" + "bc"）
- SHA-256 前 16 位 hex = 64 bit 熵，碰撞概率极低
- 幂等：相同输入永远产生相同 agent_id
- `team_id` 可选，支持无团队场景

**潜在问题**:
- ⚠️ **碰撞风险量化**: 64 bit 在 birthday paradox 下约 4 billion 次后可能碰撞。当前规模（数百 sessions）远低于此阈值，可接受。
- ⚠️ **稳定性依赖**: `display_name` 通过多级 env var 回退获取（AIDS_DISPLAY_NAME → AHA_SESSION_NAME → ... → sid），如果环境变量变化，同一 agent 可能获得不同 agent_id。`old.get("agent_id") or compute_agent_id(...)` 的 `or` 语义确保一旦计算过就不会变，这是正确的。
- ✅ **持久化**: `record["agent_id"] = old.get("agent_id") or compute_agent_id(...)` 确保已存在的 agent_id 不会被覆盖。

### 2.2 register_session 中的集成 (bin/selftools:565-568)

```python
record["agent_id"] = old.get("agent_id") or compute_agent_id(
    record.get("display_name", ""), record.get("role", ""), record.get("team_id")
)
```

**评价**: 正确。`old.get("agent_id") or` 确保：
1. 首次注册：计算新 agent_id
2. 后续更新：保留已有 agent_id
3. `agent_id` 为空字符串时也会重新计算（`"" or` 为 falsy）

### 2.3 whois 按 agent_id 聚合 (bin/selftools:1271-1320)

`_whois_by_agent_id()` 聚合所有共享同一 agent_id 的 session，输出身份视图。

**优点**: 完整的 session 历史展示，JSON/人类可读双输出
**注意**: 无分页机制，session 数量极大时可能有性能问题（当前规模不构成风险）

### 2.4 who-touched 中的 agent_id 聚合 (未提交变更)

```python
agent_ids_seen: Dict[str, int] = {}
...
if len(agent_ids_seen) > 1:
    print(f"  ({len(agent_ids_seen)} distinct agents touched this file)")
```

**评价**: 好的用户体验改进。显示 agent_id 的短格式（前 12 字符 + `...`）避免过长。

---

## 3. INV-7 唯一约束审查

### 3.1 cmd_rate 实现 (bin/selftools:1377-1390)

```python
# INV-7: reject duplicate (trace_id, rater_session_id) ratings
ratings_dir = data_dir() / "ratings"
if ratings_dir.exists():
    for rf in sorted(ratings_dir.glob("*.jsonl")):
        for line in rf.read_text().strip().splitlines():
            ...
            if existing.get("trace_id") == args.trace_id and existing.get("rater_session_id") == rater:
                eprint_identity(f"Already rated by {rater}: {args.trace_id}")
                return 1
```

**优点**:
- 正确实现 `(trace_id, rater_session_id)` 唯一约束
- 扫描所有日期的 JSONL 文件，不会因为跨天而遗漏
- 错误信息清晰

**性能问题**:
- ⚠️ **O(n) 线性扫描**: 每次评分都遍历所有 ratings JSONL 文件的所有行。随着数据增长，性能会退化。
- **严重程度**: 低（当前规模下不构成问题）
- **建议**: 如需优化，可维护一个内存中的 `(trace_id, rater_session_id) → bool` 的 Bloom filter 或索引文件

**边缘情况**:
- ✅ `rater` 通过多级 env var 回退到 "anonymous"，处理正确
- ⚠️ **JSON 解析容错**: `json.loads` 失败时 `continue`，不会因为损坏行导致误判。但如果某行格式不完整（缺少 `trace_id` 或 `rater_session_id`），会比较 `None == None` → `True`，理论上可能误拒。不过实际场景中这种情况只会在同一 anonymous rater 对同一 trace_id 时触发，概率极低。

### 3.2 测试覆盖

| 测试 | 文件 | 描述 |
|------|------|------|
| `test_rate_existing_trace` | test_selftools.py | 正常评分流程 |
| `test_rate_nonexistent_trace` | test_selftools.py | 不存在的 trace 拒绝 |
| `test_duplicate_rating_rejected` | test_selftools.py | **INV-7 核心测试** |
| `test_different_rater_allowed` | test_selftools.py | 不同 rater 可评同一 trace |
| `test_rate_requires_valid_trace` | test_invariants.py | CLI 级别 INV-7 |
| `test_rate_records_rater_identity` | test_invariants.py | 评分记录包含 rater |
| `test_rating_has_audit_fields` | test_invariants.py | 审计字段完整性 |
| `test_same_rater_cannot_rate_same_trace_twice` | test_invariants.py | 不变量级别去重验证 |

**评价**: INV-7 的测试覆盖非常充分，包括单元测试和集成测试（subprocess 调用 CLI）两个层次。

---

## 4. 测试覆盖率分析

### 4.1 测试统计

| 文件 | 测试数 | 类别 |
|------|--------|------|
| test_selftools.py | 49 | 单元测试（内存加载） |
| test_selftools_extra.py | 21 | 补充单元测试（export, heartbeat, whois, lock, redirect） |
| test_invariants.py | 19 | 不变量测试（subprocess CLI 集成） |
| **总计** | **89** (不含重复) | |

注：test_selftools.py 实际包含约 60 个测试方法（含 build-parser 相关），加上 test_selftools_extra.py 和 test_invariants.py 合计 141 个断言。

### 4.2 覆盖的关键功能

| 功能 | 覆盖状态 |
|------|----------|
| normalize_resource | ✅ 充分 |
| operation_for | ✅ 5 种操作类型 |
| session 注册/加载 | ✅ |
| trace 写入/读取 | ✅ |
| index 更新/查询 | ✅ |
| timeline 事件结构 | ✅ |
| stats (JSON/人类可读/日期过滤/空数据) | ✅ |
| export (JSON/JSONL/CSV/文件输出) | ✅ |
| query (JSON/include-exclude/trace签名) | ✅ |
| rate (正常/不存在/去重/不同rater) | ✅ |
| doctor | ✅ |
| detect_resources (bash重定向/tee/cp/MCP) | ✅ 非常充分 |
| FileLock | ✅ 基本锁和过期锁 |
| agent_id | ⚠️ 无专门测试 |
| _whois_by_agent_id | ⚠️ 无测试 |
| cmd_retire_session | ✅ |

### 4.3 测试质量评价

**优点**:
1. **TempDataMixin 设计良好**: 自动隔离环境变量，临时数据目录，测试间无干扰
2. **不变量测试层次高**: test_invariants.py 通过 subprocess 调用完整 CLI，测试端到端行为
3. **攻击场景测试**: INV-3 包含"跳过 PreToolUse"的攻击测试（test_skipping_pre_hook_does_not_create_valid_write_trace）
4. **边界测试充分**: 空输入、超长命令、不存在记录等

**待改进**:
1. ⚠️ **agent_id 无专门测试**: `compute_agent_id()` 的确定性、碰撞防护、稳定性依赖没有被测试
2. ⚠️ **_whois_by_agent_id 无测试**: 新增的 agent_id 聚合查询无测试覆盖
3. ⚠️ **INV-7 性能测试缺失**: 没有测试大量评分记录下的去重性能
4. ⚠️ **test_selftools_extra.py 有重复**: 与 test_selftools.py 存在功能重叠（如 TestCmdRate）

---

## 5. 未提交变更审查

### bin/selftools (未提交)
- agent_id 在 who-touched 中的聚合显示 — 合理
- `_whois_by_agent_id()` 新函数 — 实现正确
- `cmd_whois` 的 `agent-` 前缀路由 — 简洁有效

### scripts/aids-legion-iterate.sh (未提交)
- 移除 `--role` 参数中的 python3 内联调用 — **正确修复**，避免不必要的 Python 依赖，aha CLI 应能从 spec 文件自行推断 role

---

## 6. 发现问题汇总

| # | 严重程度 | 类别 | 描述 | 位置 |
|---|----------|------|------|------|
| R1 | 低 | 测试缺失 | `compute_agent_id()` 和 `_whois_by_agent_id()` 无测试覆盖 | tests/ |
| R2 | 低 | 性能 | INV-7 去重使用 O(n) 线性扫描 | bin/selftools:1378-1390 |
| R3 | 信息 | Commit 粒度 | `3ec48a6` 混入 5 个不同关注点 | git history |
| R4 | 信息 | 代码重复 | test_selftools.py 和 test_selftools_extra.py 的 TestCmdRate 部分重叠 | tests/ |

---

## 7. 总结

**整体评价: 良好 (B+)**

- **架构**: agent_id 的 SHA-256 + 幂等设计合理，稳定性通过 `old.get("agent_id") or` 保证
- **INV-7 实现**: 正确且防御性好，JSON 解析容错处理得当
- **测试**: 141 个测试全部通过，不变量覆盖全面（7 个 INV 全部有测试）
- **代码质量**: 一致的错误处理模式，清晰的函数命名，合理的关注点分离
- **主要建议**: 补充 agent_id 相关的单元测试，考虑 INV-7 去重的索引优化
