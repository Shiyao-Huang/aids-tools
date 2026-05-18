# AIDS 不变量体系 — 条件不变量定义与证明思路

> 基于 Bach 推理框架的方法论：无条件命题淘汰(TIER-4)，所有不变量必须是**条件不变量**——仅在显式前提满足时成立。

## 方法论来源

Bach 项目的 22-agent 对抗推理团队确立了三条铁律：

1. **H_pre 冻结**：仅使用系统可观测的前向约束推导机制
2. **对抗审计**：每条不变量必须经红队攻击验证
3. **条件化**：所有不变量必须显式声明前提条件

AIDS 系统的不变量遵循同样的方法论：每条不变量声明前提条件，无条件版本视为已淘汰。

---

## 不变量总览

| 编号 | 不变量 | 前提条件 | Bach 对应 |
|------|--------|----------|-----------|
| INV-1 | 操作序列有序性 | trace 写入走 `append_jsonl` | BFS-SNR 方向 |
| INV-2 | 资源-会话可追溯性 | session 通过 `register_session` 注册 | BFS-identity_binding |
| INV-3 | 写前读保护 | PreToolUse hook 正常触发 | BFS-forge_cost |
| INV-4 | 操作链不可篡改 | trace 文件仅 append | BFS-ACI |
| INV-5 | 身份传播完整性 | session_id 环境变量注入成功 | BFS-identity_binding |
| INV-6 | Hash 链完整性 | 写操作记录 pre_hash + post_hash | BFS-forge_cost |
| INV-7 | Goodhart 防护有效性 | 评分系统审计频率 × 结果绑定 > 0 | I-038 Goodhart 率 |

---

## INV-1：操作序列有序性

### 命题

> **若** trace 写入通过 `append_jsonl` 走 `FileLock` 加锁，**则**同一 trace 文件中的记录按时间戳严格非递减排列。

### 形式化

```
∀ r₁, r₂ ∈ traces/YYYY-MM-DD.jsonl:
  pos(r₁) < pos(r₂)  ⟹  r₁.timestamp ≤ r₂.timestamp
```

### 证明思路

1. `append_jsonl` 使用 `FileLock` 保证互斥写入（fcntl.LOCK_EX 或 os.rename 原子操作）
2. `now_ms()` 在每次 `append_jsonl` 调用时获取，单调递增（系统时钟保证）
3. 文件以 append 模式打开，新记录追加到末尾
4. 因此位置顺序 = 时间顺序

### 失效条件

- 系统时钟被手动回调
- 绕过 `append_jsonl` 直接写文件（外部工具）
- FileLock 超时导致并发写入（但 `_break_stale_lock` 检测死进程）

---

## INV-2：资源-会话可追溯性

### 命题

> **若** 资源索引通过 `update_index` 更新，**则**每条索引记录包含有效的 `last_actor`（session_id）和 `last_actor_role`。

### 形式化

```
∀ idx ∈ index/*.json:
  idx.total_ops > 0  ⟹  idx.last_actor ≠ null ∧ idx.last_actor_role ≠ null
```

### 证明思路

1. `update_index` 在 `cmd_hook_post_tool_use` 中被调用
2. 调用前 `register_session` 已执行，确保 session 有效
3. `update_index` 直接从 trace 和 session 字段填充 `last_actor` 和 `last_actor_role`
4. trace.session_id 由 `session_id_from()` 生成，保证非空

### 失效条件

- 手动修改 index JSON 文件
- session 注册失败但 trace 仍然写入

---

## INV-3：写前读保护（Stale-Write Protection）

### 命题

> **若** PreToolUse hook 正常触发且工具属于 `WRITE_TOOL_NAMES`，**则**写操作发生前，系统已检索该资源的最近 trace 链并注入为 hook 输出。

### 形式化

```
∀ trace ∈ traces/*.jsonl:
  trace.operation ∈ {create, modify, delete}
  ⟹ ∃ pending ∈ pending/*.json:
       pending.tool_use_id = trace.tool_use_id
       ∧ pending.timestamp ≤ trace.timestamp
```

### 证明思路

1. `cmd_hook_pre_tool_use` 在写工具触发时调用 `save_pending`
2. `save_pending` 记录 `pre_hash`（文件写入前的 SHA-256）
3. `cmd_hook_post_tool_use` 读取 pending，对比 `post_hash`
4. pending 的 timestamp 严格小于 trace 的 timestamp（因为 Pre 先于 Post 触发）

### 失效条件

- Hook 未安装或被跳过（直接调用 CLI 绕过 hook）
- pending 文件被手动删除

---

## INV-4：操作链不可篡改

### 命题

> **若** trace 数据仅通过 `append_jsonl` 写入且文件权限未被外部修改，**则**已写入的 trace 记录不可被覆盖或删除（仅可追加）。

### 形式化

```
∀ trace_id:
  once ∃ r ∈ traces/*.jsonl: r.trace_id = trace_id
  ⟹ ∀ future_state: r ∈ future_state(traces/*.jsonl)
```

### 证明思路

1. `append_jsonl` 以 `"a"` 模式打开文件（append-only）
2. `FileLock` 防止并发覆盖
3. trace 文件按日期分区（YYYY-MM-DD.jsonl），历史文件不再修改
4. `write_json_atomic` 用于 index 和 session，使用 `os.replace` 原子替换

### 失效条件

- 外部程序直接修改 JSONL 文件（truncate/overwrite）
- 文件系统级别损坏

---

## INV-5：身份传播完整性（自指覆盖）

### 命题

> **若** session 通过 `cmd_hook_session_start` 注册且 `CLAUDE_ENV_FILE` 可写，**则**后续所有 hook 调用中 `session_id_from()` 返回一致的 session_id。

### 形式化

```
∀ event₁, event₂ in same session:
  session_id_from(event₁) = session_id_from(event₂)
```

### 证明思路

1. `cmd_hook_session_start` 将 `AIDS_SESSION_ID` 写入 `CLAUDE_ENV_FILE`
2. Claude Code 在后续 hook 调用中自动加载环境变量
3. `session_id_from()` 优先读 `AIDS_SESSION_ID` 环境变量
4. 因此同一 session 的所有事件共享同一 session_id

### 失效条件

- `CLAUDE_ENV_FILE` 不可写（权限问题）
- 环境变量被外部覆盖
- Codex runtime 不支持 `CLAUDE_ENV_FILE`（使用 `AID_SESSION_ID` 或 `SESSION_ID` 作为回退）

---

## INV-6：Hash 链完整性

### 命题

> **若** 资源路径不是 `bash:` 或 `mcp:` 前缀，**则**写操作的 trace 包含有效的 `pre_hash` 和 `post_hash`，且 `pre_hash` 等于同一文件上一次写操作的 `post_hash`。

### 形式化

```
∀ trace₁, trace₂ ∈ traces for resource R (R ∉ {bash:*, mcp:*}):
  trace₁.timestamp < trace₂.timestamp
  ∧ trace₁.operation ∈ {create, modify}
  ∧ trace₂.operation ∈ {create, modify}
  ⟹ trace₁.post_hash = trace₂.pre_hash
```

### 证明思路

1. PreToolUse 时 `sha256_file` 计算当前文件 hash → `pre_hash`
2. 工具执行（写操作）
3. PostToolUse 时 `sha256_file` 计算新文件 hash → `post_hash`
4. 下一次写操作的 `pre_hash` 必然等于上一次的 `post_hash`（文件未变）

### 失效条件

- 两次写操作之间有外部程序修改了文件（hash 链断裂，但这也正是检测 stale write 的机制）
- 文件被删除后重建（`pre_hash = None`，表示"无前状态"）

---

## INV-7：Goodhart 防护有效性

### 命题

> **若** 评分系统（ratings）被使用且审计频率 > 0，**则**评分记录包含 rater 身份，且每个 trace 最多被同一 rater 评分一次。

### 形式化（Bach I-038 映射）

```
Goodhart_rate ∝ (stakes × manipulability × proxy_distance) / (audit × outcome_binding × penalty)
```

AIDS 实现中的对应：
- `audit` = `cmd_rate` 强制要求 trace_id 存在 + rater_session_id 非空
- `outcome_binding` = rating 绑定到具体 trace（不可泛化评价）
- `penalty` = bad rating 可被 `who-touched` 查询到，影响后续 agent 决策

### 证明思路

1. `cmd_rate` 验证 `read_trace(args.trace_id)` 存在
2. rater 身份从 `AIDS_SESSION_ID` 环境变量获取
3. rating 记录写入 `ratings/YYYY-MM-DD.jsonl`（append-only，不可篡改）
4. 通过 `op-chain` 或 `who-touched` 可查看 resource 的评分历史

### 失效条件

- rating 写入后文件被篡改
- rater 使用匿名 session_id

---

## 与 Bach 命题的映射关系

```
AIDS INV-1 (有序性)        ← Bach BFS-SNR 方向（时间序列完整性）
AIDS INV-2 (可追溯性)      ← Bach BFS-identity_binding
AIDS INV-3 (写前读保护)    ← Bach BFS-forge_cost（stale write = forge）
AIDS INV-4 (不可篡改)      ← Bach BFS-ACI（问责控制完整性）
AIDS INV-5 (身份传播)      ← Bach BFS-identity_binding（自指覆盖）
AIDS INV-6 (Hash 链)       ← Bach BFS-forge_cost（完整性验证）
AIDS INV-7 (Goodhart 防护) ← Bach I-038 Goodhart 率公式
```

---

## 验证策略

自动化验证脚本 `tests/test_invariants.py` 使用 Python unittest 框架：

1. 创建临时 `~/.aids-test-{uuid}` 数据目录
2. 通过 subprocess 调用 `bin/selftools` 执行完整 hook 流程
3. 验证每条不变量在正常流程下成立
4. 验证不变量在边界条件下（空数据、并发、缺失字段）的行为

零依赖原则：仅使用 Python 标准库。
