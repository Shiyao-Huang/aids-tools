# AIDS 系统定理验证指南

> 基于 Bach 形式化推理团队（22-agent adversarial reasoning）的综合报告
> 源目录：`/Users/copizzah/Desktop/work/bach/bach-orchestra-frontend-new-1/reasoning/`
> 生成日期：2026-05-18

---

## 1. Bach 推理框架摘要

### 1.1 研究问题

Bach 项目研究一个核心问题：**当 AI 系统的生成能力持续超越验证能力时，协作与信任机制如何演化？** 具体拆解为四个子问题：

1. 生成成本下降而验证成本未同步下降时，系统承受什么压力？
2. 伪造/作弊在什么条件下可以被有效抑制？
3. 信号噪声比（SNR）是否必然坍塌？
4. 指标优化是否必然导致 Goodhart 退化？

### 1.2 方法论：红蓝对抗 + 条件不变量

Bach 采用**红蓝对抗**范式：

- **蓝队**：建立核心命题、BFS 五不变量、压力函数模型，给出 Lean 4 形式化骨架
- **红队**：系统搜索最强反例，击穿无条件版本，收窄命题边界
- **分级**：对每个命题执行形式一致性（F）、实证支撑（E）、反例耐受（R）三重检验，按存活率分级

核心方法论铁律：

1. **$H_\text{pre}$ 冻结**：仅使用行为者可观测的前向约束推导机制，禁止事后回填前提
2. **对抗审计**：每条核心命题必须经 Red Team 攻击 + Blue Team 防守双重审查
3. **条件化**：所有不变量必须显式声明前提条件；无条件命题降级为 TIER-4（淘汰）

### 1.3 最小符号表

| 符号 | 含义 | AIDS 对应 |
|------|------|----------|
| $C_{\text{gen}}(t)$ | 生成/伪造边际成本 | agent 生成 trace、修改文件、提交 claim 的成本 |
| $C_{\text{ver}}(t)$ | 验证边际成本 | who-touched / op-chain / replay 验证的成本 |
| $F(t)$ | 有效伪造惩罚 | `$C_{\text{acquire}} + C_{\text{adapt}} + C_{\text{pass}} + C_{\text{hide}} + E[\text{sanction}]$` |
| $V(t)$ | 验证容量 | 单位时间 aids 可靠验证的操作数 |
| $S(t)$ | 信号速率 | 真能力/真协作信号速率 |
| $N(t)$ | 噪声速率 | 伪造、污染、错误 claim 速率 |
| $\text{SP}(t)$ | 选择压力 | `C_ver - C_gen` 或 `N/V` |
| $\text{IB}(t)$ | 身份绑定强度 | 输出与 session/machine/task/trace 的绑定 |
| $\text{ACI}(t)$ | 问责控制完整性 | 控制面、审计面完整程度 |

### 1.4 TIER 评分体系

每个命题按 F/E/R 三重检验打 0-2 分：

```
survival_score = (F + E + R) / 6
```

| TIER | 等级 | 标准 |
|------|------|------|
| 1 | 形式化 + 经验验证 | Lean 证明 + 历史数据/实验支撑 |
| 2 | 形式化或有条件验证 | Lean 证明或对抗审计 PASS |
| 3 | 有条件论证 | 逻辑自洽但缺乏形式化或经验验证 |
| 4 | 淘汰 | 无条件命题或已被反驳 |

映射规则：`>=0.83 → TIER-1`；`0.67-0.82 → TIER-2`；`0.50-0.66 → TIER-3`；`<0.50 → TIER-4`。

---

## 2. 可移植到 AIDS 的定理与原则

### 2.1 TIER-1 核心命题（可直接应用）

#### 命题 B-1：选择压力上升

> 若生成成本持续下降且验证成本未同步下降，则选择压力 `SP = C_ver - C_gen` 严格递增。

**AIDS 应用**：随着 agent 数量增长、自动化操作增多，每个操作的生成成本（写文件、修改配置）趋近于零。如果 AIDS 的验证能力（who-touched 查询、op-chain 回溯、trace replay）不同步增强，系统将面临选择压力上升——低质量/冲突操作会越来越难被发现。

**设计启示**：
- AIDS 必须让验证成本随生成成本同步下降（自动化 who-touched、op-chain 索引）
- 每次写操作的 trace 必须可自动 replay，而非需要人工审计
- 验证容量 `V` 必须通过自动化（CI gate、replay checker）扩容

#### 命题 B-2：伪造成本抑制噪声

> 若 `cheatingPayoff < forgeCost + expectedSanction` 且系统将威慑条件转化为噪声抑制响应，则噪声不再上升。

**AIDS 应用**：当 agent 可以轻易修改文件并声称"这是我做的"（低 forgeCost）且无制裁机制时，噪声（错误 claim、冲突修改）会持续上升。AIDS 通过 session_id + machine_id + task_id + trace hash 的绑定，提高了伪造成本——你不能冒充别人的操作。

**设计启示**：
- 每次写入必须绑定身份（session, principal, machine, task）
- 评分系统（`aids rate`）提供制裁机制（bad rating = future warning）
- `who-touched` 查询使伪造可被发现，提高 expected sanction

#### 命题 I-037：有效信息容量

> 有效信息近似由信道容量与 SNR 共同决定：`I_eff ≈ C × SNR`。容量增加但 SNR 下降时，有效信息可能下降。

**AIDS 应用**：操作 trace 数据量（容量 C）可以很大，但如果噪声（无关操作、低质量修改、重复 standby 消息）也很大，有效信息反而下降。AIDS 的 `op-chain` 和 `who-touched` 必须过滤噪声，提供高 SNR 的操作视图。

**设计启示**：
- 不是记录越多越好——信号质量比数据量更重要
- `op-chain` 应按资源过滤，只展示与目标文件相关的操作链
- rating 系统帮助区分高质量操作（good rating）和低质量操作（bad rating）

### 2.2 TIER-2 稳健推断

#### BFS 条件不变量（5 条）

Bach 将 BFS 五不变量从"必然定律"改写为**条件不变量**：

| 不变量 | 条件化表述 | AIDS 实现映射 |
|--------|-----------|--------------|
| SNR 方向 | `dN/dt > dV_eff/dt` 时 SNR 下降 | 操作噪声增速 > who-touched 验证能力增速时，trace 质量下降 |
| forge_cost | 防御层独立且提高 attacker/honest cost ratio 时有效惩罚递增 | AIDS 的 session binding + trace hash + rate 评分组成防御层 |
| identity_binding | agent/proxy 增速 > binding 协议增速时 IB 弱化 | 多 agent 并发操作时必须加强身份绑定（resource-type guard） |
| ACI | 行动面扩张快于控制/审计面时 ACI 退化 | agent 权限必须最小化 + temporal grant + scope 限制 |
| variety_gap | attack variety 增速 > verifier variety 增速时 gap 扩大 | 新的冲突模式必须被转化为 regression test 或 guard pattern |

**核心反转机制**（AIDS 已实现或可实现）：
- `who-touched` / `op-chain` → SNR 可维持（fresh sealed tasks 类效）
- trace hash + session binding → forge_cost 可递增（signed trace 类效）
- resource-type guard → IB 可增强（identity binding 类效）
- 最小权限 + TTL → ACI 可增强（policy-as-code 类效）

### 2.3 Goodhart 防护原则

> Goodhart 退化速率 ∝ (stakes × manipulability × proxy_distance) / (audit_probability × update_rate × outcome_binding × penalty)

**AIDS 应用**：
- 审计频率 × 结果绑定的联合效应，远大于单独提高任一因子
- `aids rate` 是审计机制的实现
- trace 绑定是 outcome binding 的实现
- 避免单一指标（如"完成任务数"）作为唯一评估维度

---

## 3. AIDS 系统不变量定义

基于 Bach 框架，以下定义 AIDS 系统应维护的形式化不变量。

### 3.1 身份绑定不变量（IB）

```
∀ operation op ∈ AIDS_trace:
  op.session_id ≠ NULL
  ∧ op.machine_id ≠ NULL
  ∧ op.timestamp ≠ NULL
  ∧ op.resource ≠ NULL
  ∧ op.tool_name ≠ NULL
```

**验证方法**：`aids doctor` 检查所有 trace 记录是否包含完整的身份字段。

**违反后果**：无法追溯"谁做了什么"，身份漂移导致问责链断裂。

### 3.2 操作链完整性不变量（OCI）

```
∀ file f:
  op_chain(f) = sorted([op | op.resource = f], by=timestamp)
  ∧ ∀ op ∈ op_chain(f):
      op.parent_trace_id ∈ {prev_op.trace_id for prev_op in op_chain(f) before op}
```

**验证方法**：`aids op-chain <path>` 输出的操作链必须按时间单调递增，且每条 trace 有 trace_id。

**违反后果**：操作链断裂，无法重建文件修改历史。

### 3.3 验证容量覆盖不变量（VCC）

```
verification_capacity(t) ≥ noise_rate(t)
```

即 AIDS 的验证能力（who-touched 查询速度、op-chain 索引速度）必须覆盖操作生成速度。

**验证方法**：`aids stats` 检查操作速率和查询速率的比例。

**违反后果**：trace 积压，查询延迟上升，系统进入"追不上"状态。

### 3.4 伪造成本抑制不变量（FCD）

```
forge_cost(session_binding + trace_hash + rate_sanction) > cheating_payoff(anonymous_modify)
```

即通过 AIDS 绑定机制，匿名/伪造操作的成本必须高于使用真实身份操作的成本。

**验证方法**：检查是否有未绑定的操作（`aids who-touched` 返回 unknown session）。

**违反后果**：噪声操作上升，SNR 下降，trace 数据可信度降低。

### 3.5 协作稳定性不变量（CS）

```
∀ concurrent_write cw to file f:
  pre_check(f) returns last_modifier info
  ∧ actor can see intent of last_modifier
  ∧ actor can make informed decision (proceed / wait / coordinate)
```

**验证方法**：PreToolUse hook 输出上次修改者信息；actor 在写入前可见。

**违反后果**：并发写入冲突，文件覆盖，协作信任下降。

### 3.6 反脆弱增益不变量（AF）

```
∀ attack_pattern p discovered:
  ∃ guard g ∈ AIDS_system:
    g.prevents(p) ∧ g.is_reusable ∧ g.has_regression_test
```

**验证方法**：每次发现冲突模式后，检查是否已转化为 guard（hook 规则、schema 验证、regression test）。

**违反后果**：同一冲突模式反复出现，系统只有 resilience（恢复）而非 antifragility（变强）。

---

## 4. 验证方法和检查点

### 4.1 日常验证（每次对话启动）

| 检查点 | 命令 | 期望输出 | 不变量 |
|--------|------|---------|--------|
| 身份注册 | `aids register-session` | session_id 已记录 | IB |
| 当前身份 | `aids who-touched .` | 当前 session 可见 | IB |
| 系统健康 | `aids doctor` | 所有检查 PASS | IB, OCI |

### 4.2 操作前验证（PreToolUse hook）

| 检查点 | 触发条件 | 期望行为 | 不变量 |
|--------|---------|---------|--------|
| 修改前查询 | 任何 Write/Edit 工具调用 | 显示文件上次修改者、意图、rating | CS |
| 身份注入 | session 启动 | 显示"你是 N 号 agent，角色 X" | IB |
| 影响范围 | 修改核心文件时 | 显示调用者、依赖关系 | ACI |

### 4.3 操作后验证（PostToolUse hook）

| 检查点 | 触发条件 | 期望行为 | 不变量 |
|--------|---------|---------|--------|
| Trace 记录 | 任何工具调用 | trace 写入 `~/.aids/traces/` | OCI |
| 索引更新 | 文件修改操作 | `~/.aids/index/` 更新 | OCI |
| 操作评分 | 用户/agent 评分 | rating 写入 trace | FCD |

### 4.4 周期验证（定期运行）

| 检查点 | 频率 | 方法 | 不变量 |
|--------|------|------|--------|
| 操作链完整性 | 每日 | 遍历 index 检查 trace_id 连续性 | OCI |
| 身份绑定覆盖率 | 每日 | 统计 NULL session 的 trace 比例 | IB |
| 验证容量 vs 噪声率 | 每周 | `aids stats` 对比操作速率和查询速率 | VCC |
| 评分分布 | 每周 | good/bad/uncertain 比例 | FCD |
| 冲突模式回顾 | 每月 | 检查发现的冲突是否已转化为 guard | AF |

### 4.5 形式化验证骨架（Lean 风格）

以下是基于 Bach 项目的 Lean 验证骨架，可移植到 AIDS 场景：

```lean
-- AIDS 最小模型
namespace AIDSFormal
  abbrev SessionID := String
  abbrev TraceID := String
  abbrev Timestamp := Nat

  structure Operation where
    sessionId : SessionID
    traceId : TraceID
    resource : String
    toolName : String
    timestamp : Timestamp
    rating : Option String  -- "good" / "bad" / "uncertain"

  -- 不变量 1：身份绑定
  def IdentityBound (ops : List Operation) : Prop :=
    ∀ op ∈ ops, op.sessionId ≠ "" ∧ op.traceId ≠ ""

  -- 不变量 2：操作链时间单调
  def Chronological (ops : List Operation) : Prop :=
    ∀ i j, i < j → (ops.get! i).timestamp ≤ (ops.get! j).timestamp

  -- 不变量 3：伪造成本抑制
  -- 若所有操作都有绑定，则未绑定操作的成本 > 绑定操作成本
  def ForgeCostDeterrence (ops : List Operation) : Prop :=
    IdentityBound ops ∧
    ∀ op ∈ ops, op.rating = some "bad" →
      -- bad rating 的操作被标记，后续 agent 可见
      True  -- 实际实现需要制裁机制的形式化

end AIDSFormal
```

### 4.6 反脆弱检查清单

Bach 报告的核心条件：**反脆弱只在攻击结果被转化为可复用约束时成立**。

| 攻击/冲突类型 | 转化目标 | AIDS 实现 |
|--------------|---------|----------|
| 并发写入冲突 | resource lock guard | FileLock in bin/selftools |
| 身份漂移 | resource-type guard | session_id + machine_id 绑定 |
| 错误 claim | evidence-backed completion | task lifecycle: start → plan → evidence → complete |
| 权限滥用 | temporal grant + scope | TTL + audit reason + @granted opt-in |
| 操作伪造 | replay checker | trace hash + who-touched 验证 |

---

## 5. 从 Bach 到 AIDS 的设计原则映射

### 5.1 五条核心设计原则

基于 Bach 报告第 8 节"反脆弱验证与防御设计原则"：

1. **验证从"结果分数"迁移到"可重放过程"**
   - Bach：验证应基于 sealed environment + fresh task + replay evidence
   - AIDS：`op-chain` 提供可重放过程，`who-touched` 提供身份证据

2. **伪造成本与真实生产成本重新耦合**
   - Bach：提高 attacker/honest cost ratio，而非增大用户摩擦
   - AIDS：session binding + trace hash 使伪造 trace 比真实操作更难

3. **每次写入绑定身份**
   - Bach：session、principal、machine、task、transcript hash
   - AIDS：PreToolUse/PostToolUse hook 自动注入 session_id + machine_id

4. **每个控制动作可解释**
   - Bach：scope + expiry + replay evidence
   - AIDS：`aids doctor` + `aids who-touched` + trace 审计

5. **攻击 variety 转化为防御 variety**
   - Bach：把每次攻击转成 regression test 或 guard pattern
   - AIDS：发现的冲突模式转化为 hook 规则或 FileLock 策略

### 5.2 协作稳定性的通用条件

Bach 推导的跨时代通用均衡条件：

```
cheatingPayoff ≤ q × sanction + forge_cost + future_value_loss
```

AIDS 翻译：

```
匿名修改的收益 ≤ 被发现概率 × bad_rating后果 + 伪造trace成本 + 未来协作信任损失
```

当这个不等式成立时，使用 AIDS 身份系统的真实操作是 agent 的最优策略。

### 5.3 相变阈值预警

Bach 识别了三个相变阈值，AIDS 应监控：

| 阈值 | 条件 | AIDS 预警信号 |
|------|------|--------------|
| A：作弊期望值从负转正 | forge_cost + sanction < cheating_payoff | 未绑定操作比例上升 |
| B：验证容量低于生成容量 | claim_rate > verification_capacity | trace 积压、查询延迟 |
| C：身份绑定弱于 agent 增长 | new_agents/session > binding_protocol_updates | unknown session 比例上升 |

---

## 6. 实施建议

### 6.1 短期（立即可做）

1. **`aids doctor` 增加不变量检查**：检查 IB、OCI、VCC 三条不变量
2. **PreToolUse hook 显示评分**：写入前显示文件上次操作的 rating（如果有的话）
3. **`aids stats` 增加 SNR 指标**：显示 good/bad/uncertain 操作比例

### 6.2 中期（本周内）

4. **实现反脆弱闭环**：发现的冲突模式自动转化为 hook 规则
5. **增加相变阈值监控**：`aids stats` 显示三个阈值的当前状态
6. **trace schema 验证**：确保每条 trace 满足身份绑定不变量

### 6.3 长期（持续改进）

7. **Lean 风格不变量验证**：将核心不变量写成可机器检查的形式
8. **跨 agent 协作均衡分析**：用博弈论分析多 agent 场景下的均衡条件
9. **Goodhart 防护**：多维度评估而非单一"完成任务数"指标

---

## 附录 A：Bach 项目文件清单

| 文件 | 状态 | 内容 |
|------|------|------|
| `synthesis-report.tex` | PASS | 综合报告：命题、分级、Lean 骨架、跨域证据 |
| `conclusion-report.tex` | PASS | 结论报告：43 洞察、对抗审计、BFS 条件不变量 |
| `lean-proofs.lean` | PASS | T1-T3 Lean 4.29.1 骨架，0 sorry，0 error |
| `lean-proofs-notes.md` | PASS | 形式化注释与后续加强方向 |
| `adversarial/blue-team-BFS-pressure-defense.md` | PASS | BFS 防御 + 压力函数 + 反脆弱检验 |
| `adversarial/proposition-survival-ranking.md` | PASS | 21 命题三重检验分级 |
| `adversarial/red-team-I031-I033-I037-I038.md` | PASS | 红队四命题反证 |
| `adversarial/game-theory-collaboration-models.md` | CONDITIONAL | 8 时代博弈模型 |
| `adversarial/lean-formalization-support.md` | PASS | 博弈/分化命题形式化支援 |

## 附录 B：关键参考

1. Kiela et al., "Dynabench: Rethinking Benchmarking in NLP," arXiv 2021
2. Gneiting & Raftery, "Strictly Proper Scoring Rules, Prediction, and Estimation," JASA 2007
3. Ratnieks & Visscher, "Worker policing in the honeybee," Nature 342, 1989
4. Wilkinson, "Reciprocal food sharing in the vampire bat," Nature 308, 1984
5. Campbell, "Assessing the impact of planned social change," 1979
