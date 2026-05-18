# LEGION3 AIDS 数据分析报告

> 分析日期: 2026-05-18
> 数据来源: ~/.aids/{traces,ratings,sessions,timeline,index,pending}

---

## 1. 概览

| 指标 | 数值 |
|------|------|
| 总 trace 数 | 1,508 (2026-05-18) |
| 总 session 数 | 108 |
| 总 rating 数 | 3 |
| Timeline 事件 | 1,515 |
| 文件索引条目 | 847 |
| 待处理 trace | 283 |
| 数据总大小 | ~1.9 MB |

---

## 2. 工具使用模式

### 2.1 工具调用分布

| 工具 | 调用次数 | 占比 |
|------|---------|------|
| Bash | 1,010 | 67.0% |
| Read | 345 | 22.9% |
| Edit | 100 | 6.6% |
| aids_who_touched | 22 | 1.5% |
| Write | 16 | 1.1% |
| apply_patch | 15 | 1.0% |

**发现**: Bash 占绝对主导 (67%)，Read 次之 (23%)，写入操作 (Edit+Write+apply_patch) 合计仅 8.7%。这是一个**以探索/执行为主**的工作模式，写入操作相对稀少。

### 2.2 操作类型

| 操作 | 次数 |
|------|------|
| execute | 989 |
| read | 345 |
| modify | 113 |
| touch | 41 |
| create | 20 |

### 2.3 时序模式

```
01:00 [ 533] ████████████████████████████████████████  ← 深夜高产
02:00 [  52] ████
04:00 [   8] █
06:00 [   6] █
08:00 [   6] █
10:00 [ 356] ████████████████████████████  ← 上午高产
11:00 [ 492] ████████████████████████████████████████  ← 最高峰
12:00 [  55] ████
```

**发现**: 两个活跃高峰 — 凌晨 01:00 (533 ops) 和 上午 10-11:00 (848 ops)。这暗示**自动化/定时任务**在凌晨运行，人类驱动的工作集中在上午。

---

## 3. 会话分析

### 3.1 运行时分布

| 运行时 | 会话数 | 占比 |
|--------|--------|------|
| claude | 91 | 84.3% |
| codex | 8 | 7.4% |
| bash | 8 | 7.4% |
| unknown | 1 | 0.9% |

### 3.2 角色分布

| 角色 | 会话数 |
|------|--------|
| supervisor | 34 |
| unknown | 24 |
| implementer | 21 |
| architect | 6 |
| reviewer | 6 |
| scout | 3 |
| master | 3 |
| builder | 2 |
| qa-engineer | 2 |
| researcher | 2 |

**发现**: supervisor (34) 是最活跃的角色，implementer (21) 次之。**24 个 session 角色为 unknown** — 这意味着近 22% 的会话没有正确注入角色信息。

### 3.3 模型使用

| 模型 | 会话数 |
|------|--------|
| (未记录) | 90 |
| claude-sonnet-4-6 | 10 |
| gpt-5.4 | 2 |
| gpt-5.5 | 2 |
| gpt-5.4-mini | 2 |
| claude-opus-4-6 | 1 |

**发现**: 83% 的会话没有记录模型信息 (model=None)。这是数据完整性的一个缺口。

### 3.4 项目分布

| 项目 | 会话数 |
|------|--------|
| selftools | 53 |
| cluster | 31 |
| bach-orchestra-frontend (reasoning) | 16 |
| bach-orchestra-frontend | 2 |
| me | 2 |
| selfloopbash | 1 |

### 3.5 Agent ID 稳定性

- 104/108 (96.3%) 的会话没有 agent_id
- 仅 4 个会话有稳定的 agent_id (3 个唯一 agent)

**发现**: agent_id 采用率极低，几乎无法追踪跨会话的同一 agent 行为。

---

## 4. 评分分析

### 4.1 评分数据

| trace_id | 评分 | 评论 | 时间 |
|----------|------|------|------|
| tr_9c60b2582ac1 | good | README读取正常，who-touched能查到 | 05-17 17:19 |
| tr_9c60b2582ac1 | good | useful read trace | 05-18 02:02 |
| tr_0100d9d62910 | good | direct usage smoke test | 05-18 02:51 |

**发现**: 仅有 3 条评分，全部为 "good"。评分数据极度稀疏，尚不足以支撑趋势分析。一个 trace 被重复评分 (tr_9c60b2582ac1)。

---

## 5. 数据质量评估

### 5.1 哈希完整性

| 字段 | 存在率 |
|------|--------|
| pre_hash | 31.6% |
| post_hash | 10.1% |
| metadata | 100% |

**发现**: 哈希覆盖率低。pre_hash 仅覆盖 31.6%，post_hash 仅 10.1%。这意味着大部分写入操作缺乏完整性校验，无法进行事后的一致性审计。

### 5.2 结果追踪

- 仅 8/1,508 (0.5%) 的 timeline 事件包含结构化 result 字段
- 所有记录的 result 均为成功 (exit_code=0)
- 无失败记录

### 5.3 待处理积压

- 283 个 pending trace 未被索引
- 1 个 stale lock 文件

---

## 6. 改进建议

### 6.1 高优先级

1. **提升 agent_id 采用率**
   - 当前 96.3% 的会话没有 agent_id
   - 建议: 在 session-start hook 中强制注入 agent_id，确保跨会话追踪可行
   - 影响: 行为分析、评分聚合、agent 演进均依赖此字段

2. **填充 model 字段**
   - 83% 的会话 model=None
   - 建议: 从 Claude/Codex 的环境变量中提取模型信息并注入
   - 影响: 成本分析、性能归因需要模型粒度

3. **补充 role 字段**
   - 22% 的会话 role="unknown"
   - 建议: 验证 hook 注入逻辑，确保 AHA_SPEC_ID 或 --role 参数正确传递

### 6.2 中优先级

4. **提升哈希覆盖率**
   - 当前 pre_hash 仅 31.6%，post_hash 仅 10.1%
   - 建议: 对 Read/Write/Edit/Bash 工具统一计算文件哈希
   - 影响: 支持变更审计和冲突检测

5. **结果追踪增强**
   - 仅 0.5% 的事件有结构化 result
   - 建议: 在 post-tool-use hook 中捕获 tool_use_result 的核心字段
   - 影响: 支持成功率统计和错误模式分析

6. **处理 pending 积压**
   - 283 个 pending trace 待处理
   - 建议: 增加索引批处理频率或检查积压原因
   - 影响: 索引完整性影响 aids_who_touched 等查询的准确性

### 6.3 低优先级

7. **评分激励机制**
   - 仅有 3 条评分，数据稀疏
   - 建议: 在 CLI 中增加评分提示，或自动根据操作结果生成建议评分
   - 影响: 评分数据是反馈循环的基础

8. **清理 stale locks**
   - 1 个 stale lock 文件
   - 建议: 在 session-start 时增加 lock GC

9. **数据格式统一**
   - traces/ 同时存在 .jsonl 和 .ndjson 格式
   - 建议: 统一为 .jsonl，迁移旧数据

---

## 7. 架构观察

### 7.1 运行时架构

```
~/.aids/
├── sessions/    # 108 个会话文件 (JSON), 含 .current 符号链接
├── traces/      # 按 JSONL 日期分区 (1,508 条)
├── timeline/    # 按 JSONL 日期分区 (1,515 条, 含 schema_version)
├── index/       # 847 个 Base64 编码的文件路径索引
├── ratings/     # 按日期分区的 JSONL
├── pending/     # 283 个待索引 trace
└── locks/       # fcntl.flock 锁文件
```

### 7.2 数据流

```
Hook (pre/post-tool-use) → trace → pending/ → index/
                                              → timeline/
                                              → ratings/ (人工)
```

### 7.3 性能观察

- 系统每日处理 ~1,500 条 trace，数据量 ~1.9 MB
- 平均 trace 处理延迟 ~14ms (仅 20 条有记录)
- 当前规模下性能不是瓶颈

---

## 8. 总结

AIDS 系统已具备完整的 trace/session/rating 数据采集管线，但存在三个核心数据质量问题：

1. **身份追踪断裂**: agent_id (3.7%) 和 model (17%) 覆盖率过低
2. **结果不可观测**: 仅 0.5% 的事件有结构化 result
3. **反馈循环薄弱**: 仅 3 条评分，无法形成有效的 agent 演进信号

建议优先修复身份注入链 (agent_id + model + role)，再增强结果追踪和评分机制。
