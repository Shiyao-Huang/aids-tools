# Legion5 AIDS 数据分析报告

> 分析日期: 2026-05-18
> 分析者: Legion5 Researcher (agent-0cc4b35d6ab31e79)
> 数据源: `~/.aids/traces/`, `~/.aids/ratings/`, `~/.aids/sessions/`

---

## 1. 数据概览

| 维度 | 数值 |
|------|------|
| Trace 记录总数 | 1,788 条 (2026-05-18) + 1 条 (2026-05-17) |
| Trace 文件大小 | 2.4 MB |
| Session 文件数 | 147 个 |
| Rating 记录数 | 4 条 |
| 活跃时间跨度 | ~24 小时 (2026-05-17 17:00 ~ 2026-05-18 22:00) |

---

## 2. Traces 分析

### 2.1 操作类型分布

| 操作 | 次数 | 占比 |
|------|------|------|
| execute | 1,213 | 67.8% |
| read | 378 | 21.1% |
| modify | 126 | 7.0% |
| touch | 50 | 2.8% |
| create | 21 | 1.2% |

**发现**: 操作以执行 (execute) 为主，读操作占 1/5，写操作 (modify + create) 仅占 8.2%。说明 agent 活动以「运行命令 + 读取文件」为核心循环，实际文件修改较少。

### 2.2 工具使用分布

| 工具 | 次数 | 占比 |
|------|------|------|
| Bash | 1,277 | 71.4% |
| Read | 363 | 20.3% |
| Edit | 101 | 5.6% |
| mcp__aids__aids_who_touched | 28 | 1.6% |
| apply_patch | 28 | 1.6% |
| Write | 16 | 0.9% |
| mcp__aids__aids_op_chain | 2 | 0.1% |
| mcp__aids__aids_doctor | 1 | 0.1% |

**发现**:
- Bash 占绝对主导地位 (71.4%)
- AIDS 自有工具 (`who_touched`, `op_chain`, `doctor`) 使用率仅 1.7%
- `apply_patch` 是 Codex 专有工具 (28 次全部来自 Codex sessions)
- Claude 使用 Read/Edit/Write 组合，Codex 使用 Bash/apply_patch 组合

### 2.3 最高频访问文件 TOP 15

| 次数 | 文件路径 |
|------|----------|
| 191 | `bin/selftools` |
| 36 | `src/trace/trace.js` |
| 29 | `~/Desktop/cluster/bin/aids-deploy-nodes.sh` |
| 27 | `lib/session.js` |
| 24 | `tests/test_selftools.py` |
| 15 | `scripts/aids-legion-iterate.sh` |
| 14 | `mcp:mcp__aids__aids_who_touched` |
| 11 | `~/.aids/selftools/bin/selftools` |
| 9 | `tests/test_invariants.py` |
| 9 | `reasoning/five-conclusions-explained.tex` (外部项目) |
| 7 | `~/.claude/hooks/selftools-post-tool-use.sh` |
| 7 | `aid/core.py` (外部项目 selfloopbash) |

**发现**:
- `bin/selftools` 是绝对核心文件，被 **18 个不同 session** 访问
- selftools 项目自身文件 (trace.js, session.js, test_selftools.py) 占据前列
- 存在跨项目访问: cluster 项目 (29 次)、bach 项目 (9+ 次)、UIdesign 项目 (4 次)
- Hook 脚本 (post_tool_use.sh 等) 被频繁读取，因为每次工具调用都会触发

### 2.4 文件类型分布

| 扩展名 | 次数 |
|--------|------|
| (无扩展名) | 246 |
| .md | 81 |
| .sh | 79 |
| .js | 78 |
| .py | 56 |
| .tex | 18 |

### 2.5 高频 Bash 命令

| 次数 | 命令摘要 |
|------|----------|
| 30 | SSH 到 192.168.31.79 (bach docker) |
| 29 | SSH 到 192.168.31.27 (copizza2 docker) |
| 23 | SSH 到 192.168.31.27 (docker exec) |
| 20 | SSH 到 192.168.31.62 (cipizza3 docker) |
| 17 | SSH 到 192.168.31.171 (copizza) |
| 10 | `npm test` |

**发现**: SSH 部署操作占 Bash 命令的大部分 (~120 次)，表明大量 agent 活动集中在集群部署和远程操作上。

### 2.6 活跃 Session 排行 TOP 10

| Session | 操作数 | Runtime | Agent ID |
|---------|--------|---------|----------|
| 019e3921... | 123 | codex | agent-c0e954d5278287a7 |
| f8944730... | 104 | claude | (无) |
| a1ef027b... | 87 | claude | agent-6041e52b5927ba01 |
| 8ad8adbf... | 85 | claude | (无) |
| 019e36a5... | 69 | codex | agent-b1e1775c17b915fc |
| bf5ab5d4... | 67 | claude | (无) |
| e1d79e84... | 66 | claude | agent-2bf5a369ef89675f |
| 019e3a1e... | 65 | codex | agent-6965bd7901a4f616 |
| ff1e84f2... | 64 | claude | (无) |
| 01144a4a... | 58 | claude | (无) |

### 2.7 时段活动分布

| 时段 | 操作数 |
|------|--------|
| 02:00 | 356 |
| 03:00 | 492 |
| 08:00 | 177 |
| 09:00 | 114 |
| **17:00** | **533** (峰值) |

**发现**: 17:00 是全天活动高峰 (533 次)，02:00-03:00 有显著的自动化夜间活动 (848 次)。

### 2.8 跨 Session 文件竞争

| 文件 | 访问 Session 数 |
|------|-----------------|
| `bin/selftools` | **18** |
| `scripts/aids-legion-iterate.sh` | 9 |
| `src/trace/trace.js` | 9 |
| `lib/session.js` | 8 |
| `tests/test_selftools.py` | 8 |

**发现**: 36/124 (29%) 的文件被多个 session 访问。`bin/selftools` 被 18 个 session 共同访问，存在较高的并发冲突风险。

---

## 3. Sessions 分析

### 3.1 Agent ID 覆盖率

| 指标 | 数值 |
|------|------|
| 总 Session 数 | 147 |
| 有 agent_id | 45 (30.6%) |
| **缺失 agent_id** | **102 (69.4%)** |

**严重问题**: 近 70% 的 session 缺少 agent_id。这意味着大量操作无法追溯到具体的 agent 身份。

### 3.2 Runtime 分布

| Runtime | 数量 | 占比 |
|---------|------|------|
| claude | 123 | 83.7% |
| codex | 15 | 10.2% |
| bash | 8 | 5.4% |
| unknown | 1 | 0.7% |

### 3.3 Role 分布

| Role | 数量 | 占比 |
|------|------|------|
| supervisor | 42 | 28.6% |
| implementer | 33 | 22.4% |
| **unknown** | **27** | **18.4%** |
| reviewer | 8 | 5.4% |
| qa-engineer | 7 | 4.8% |
| developer | 6 | 4.1% |
| architect | 6 | 4.1% |
| master | 4 | 2.7% |
| researcher | 4 | 2.7% |
| scout | 3 | 2.0% |
| builder | 2 | 1.4% |
| 其他 (org-manager, scribe, test, tester, human) | 各 1 | 5.4% |

**发现**:
- Supervisor 是最常见的角色 (28.6%)，说明团队中监控/协调开销较大
- 18.4% 的 session 角色为 "unknown"
- 去重后共 **24 个唯一 agent_id**

### 3.4 Session 记录样例结构

```json
{
  "actor_type": "agent",
  "agent_id": "agent-b1e1775c17b915fc",
  "display_name": "019e36a5-0696-7d33-a525-94f8aae993a4",
  "first_seen_at": 1779094175580,
  "model": "gpt-5.5",
  "permission_mode": "bypassPermissions",
  "role": "implementer",
  "runtime": "codex"
}
```

---

## 4. Ratings 分析

### 4.1 评分概况

| 指标 | 数值 |
|------|------|
| 总评分记录 | 4 |
| Good | 4 (100%) |
| Bad | 0 |
| Uncertain | 0 |
| **评分率** | **0.22% (4/1788)** |

### 4.2 评分内容

| 评分 | 评论 |
|------|------|
| good | README读取正常，who-touched能查到 |
| good | useful read trace |
| good | direct usage smoke test |
| good | QA test rating |

### 4.3 评分字段结构

```json
{
  "rating_id": "rt_b299bdd4d2ce",
  "trace_id": "tr_9c60b2582ac1",
  "rater_session_id": "anonymous",
  "score": "good",
  "comment": "...",
  "runtime": "unknown",
  "rater_actor_type": "unknown"
}
```

**严重问题**:
- 评分率极低 (0.22%)，1788 条 trace 中只有 4 条被评分
- 所有评分的 `rater_session_id` 为 "anonymous"，无法追溯评分者
- `rater_actor_type` 和 `runtime` 均为 "unknown"
- 100% 好评率可能是选择偏差（只有特意测试的人才会评分）

---

## 5. 关键发现汇总

### 5.1 严重问题 (HIGH)

| # | 问题 | 影响 |
|---|------|------|
| H1 | **agent_id 覆盖率仅 30.6%** | 69.4% 的 session 无法追踪身份，溯源和审计能力严重受损 |
| H2 | **Traces 中 82% 的记录 agent_id 为 unknown** | 与 session 数据呼应，大量 trace 无法关联到具体 agent |
| H3 | **评分系统形同虚设 (0.22% 使用率)** | 无足够反馈数据驱动质量改进 |

### 5.2 中等问题 (MEDIUM)

| # | 问题 | 影响 |
|---|------|------|
| M1 | **intent 字段滥用** | 大量记录的 intent 存储了完整 goal 文本甚至 patch 内容，而非结构化分类 |
| M2 | **29% 文件存在跨 session 访问** | `bin/selftools` 被 18 个 session 并发访问，但无锁机制可见 |
| M3 | **27 个 session (18.4%) 角色为 unknown** | 削弱了角色级别的行为分析能力 |
| M4 | **duration_ms 大量为 null** | 约 50% 的记录缺少执行时长数据，无法做性能分析 |

### 5.3 低级问题 (LOW)

| # | 问题 | 影响 |
|---|------|------|
| L1 | **跨项目 trace 混合** | selftools 的 trace 文件中包含 cluster、bach、UIdesign 等项目的操作记录 |
| L2 | **评分者身份缺失** | 所有评分的 rater_session_id 为 "anonymous" |
| L3 | **role 命名不统一** | test / tester / qa-engineer 可能指同一角色 |

---

## 6. 改进建议

### 6.1 优先级 P0 — agent_id 覆盖率

**问题**: 69.4% 的 session 和 82% 的 trace 缺少 agent_id。

**建议**:
1. **强制 agent_id 生成**: 在 `session-start` hook 中，如果没有检测到 agent_id，自动生成一个基于 session_id 的确定性 ID（如 `agent-<sha256(session_id)[:16]>`）
2. **Trace 写入校验**: 在 trace 记录写入时，如果 agent_id 为空，从 session 注册表自动填充
3. **定期扫描**: 添加 `aids doctor --fix` 子命令，回填历史记录中缺失的 agent_id

### 6.2 优先级 P0 — 评分系统激活

**问题**: 0.22% 的评分率无法支撑数据驱动的质量改进。

**建议**:
1. **集成评分提示**: 在 `post_tool_use` hook 中，对 modify/create 操作自动提示评分（或使用 LLM 自动评分）
2. **Session 级别总结评分**: 在 session 结束时自动生成一次评分（基于操作数量、错误率等）
3. **评分者身份修复**: 将 rater_session_id 从 "anonymous" 改为实际的 session_id
4. **最低评分配额**: 设定每个 session 至少提交 N 条评分的软性目标

### 6.3 优先级 P1 — Intent 字段规范化

**问题**: intent 字段存储了完整 goal 文本和 patch 内容。

**建议**:
1. **分类枚举**: 将 intent 限制为固定枚举值（如 `read`, `write`, `test`, `deploy`, `debug`, `research`）
2. **Goal 分离**: 将完整的 goal 文本移到 session 记录中，trace 只保留操作级别的意图
3. **自动分类**: 基于工具类型和操作类型自动推断 intent（Bash+ssh → deploy, Read → research, Edit → write）

### 6.4 优先级 P1 — 并发冲突防护

**问题**: 29% 的文件被多个 session 访问，`bin/selftools` 被 18 个 session 并发访问。

**建议**:
1. **写锁检测**: 在 modify 操作前检查是否有其他 session 已读取/修改同一文件
2. **冲突告警**: 当检测到同一文件被 >5 个 session 访问时，发出 team chat 告警
3. **操作链验证**: 加强 `aids op-chain` 命令，展示文件级别的冲突时间线

### 6.5 优先级 P2 — 数据质量提升

**建议**:
1. **统一 role 命名**: 合并 test/tester → qa-engineer，建立 role 枚举
2. **duration_ms 填充**: 在 hook 中记录工具调用的开始和结束时间，确保 duration 数据完整
3. **项目隔离**: 按 `project_path` 或 `cwd` 分离 trace 文件，避免跨项目数据混合
4. **定期数据报告**: 添加 `aids stats` 命令，输出本报告的精简版摘要

---

## 7. 数据趋势

```
活动时段分布 (2026-05-18)
00:00    6  |
02:00  356  ████████████████████
03:00  492  ████████████████████████████
04:00   55  ███
08:00  177  ██████████
09:00  114  ██████
17:00  533  ████████████████████████████████  ← 峰值
18:00   52  ███
20:00    8  |
22:00    6  |
```

```
Session 角色分布
supervisor   42  ██████████████████████
implementer  33  █████████████████
unknown      27  ██████████████  ← 需修复
reviewer      8  ████
qa-engineer   7  ███
developer     6  ███
architect     6  ███
```

```
agent_id 覆盖率
[有 ID  30.6%] ████████████
[缺失   69.4%] ████████████████████████████████  ← 严重
```

---

## 8. 结论

AIDS 系统已积累了可观的操作数据 (1,788 traces / 147 sessions)，核心追踪功能运作正常。但存在三个系统性短板：

1. **身份追溯断裂** — 近 70% 的 session 缺少 agent_id，导致大量操作成为「匿名行为」
2. **反馈循环缺失** — 评分系统几乎没有被使用，无法形成「操作 → 评价 → 改进」的闭环
3. **数据规范性不足** — intent 字段滥用、role 命名不统一、duration 数据缺失

建议按 P0 → P1 → P2 优先级逐步修复，预计 P0 问题修复后，系统的可审计性和反馈质量将显著提升。
