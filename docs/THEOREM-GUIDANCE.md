# AIDS 定理指导 — Bach 形式化推理到系统设计映射

> 从 Bach 22-agent 对抗推理综合报告提取对 AIDS 系统的设计指导
> 源文件：`synthesis-report.tex`（595 行 LaTeX）
> 生成日期：2026-05-18
> 角色：架构师（architect）

---

## 设计原则

> **所有设计必须可配置、可增减。AIDS 是 playground，策略高度解耦。**
> 每条实现建议均为**可插拔策略**，通过 `~/.aids/config.json` 开关控制。

---

## Tier-1 定理映射

### 定理 B-1：选择压力递增

- **形式化**：当 `generation_cost / verification_cost → 0` 时，系统必须提高选择门槛才能维持质量
- **直觉**：生成越便宜，垃圾越多；筛选必须越来越严
- **AIDS 当前状态**：
  - trace 记录无门槛 — 任何 agent 都可写 JSONL
  - 无质量门控：`appendTrace()` 直接追加，不检查内容
  - ratings 系统存在但无强制消费
- **差距**：无选择压力机制 — trace 产出的数量不受控制
- **实现建议**（可配置策略）：
  1. **trace 速率限制**：`~/.aids/config.json` → `trace.rate_limit_per_session`（默认无限制）
  2. **质量门控**：`trace.quality_gate` 策略 — 对高频写入者启用采样审核
  3. **淘汰策略**：`trace.eviction_policy` — 低评分 trace 按时间淘汰（可关闭）
- **配置示例**：
  ```json
  {
    "strategies": {
      "selection_pressure": {
        "enabled": false,
        "rate_limit_per_session": null,
        "quality_gate": "off",
        "eviction_policy": "none"
      }
    }
  }
  ```

---

### 定理 B-2：伪造成本抑制噪声

- **形式化**：`cheatingPayoff < forgeCost + E[sanction]` 时，作弊被有效抑制
- **直觉**：伪造代价足够高 → 作弊不划算 → 噪声被压低
- **AIDS 当前状态**：
  - trace 是 JSONL 文本 — 可手动编辑，forge cost ≈ 0
  - `aids sign` 签名存在但非强制
  - hash chain（INV-6）已定义但未实现
- **差距**：伪造成本过低 — 任何人可编辑 `~/.aids/traces/*.ndjson`
- **实现建议**（可插拔签名后端）：
  1. **签名后端策略**：`identity.signature_backend` — `["none", "hash_chain", "sqlite_ledger", "git_notes"]`
     - `none`：当前状态（开发用）
     - `hash_chain`：每条记录带 `prev_hash`，篡改破坏链
     - `sqlite_ledger`：`~/.aids/ledger.sqlite`，只 append 的表 + 触发器
     - `git_notes`：利用 git 对象不可变性
  2. **策略接口**：`SignatureBackend` 抽象类，所有后端实现相同接口
     ```python
     class SignatureBackend:
         def sign(self, record: dict) -> dict: ...
         def verify(self, records: list[dict]) -> bool: ...
         def tamper_evidence(self, records: list[dict]) -> list[str]: ...
     ```
  3. **`aids verify`** 命令：检查链完整性，报告篡改证据
- **配置示例**：
  ```json
  {
    "strategies": {
      "signature": {
        "backend": "hash_chain",
        "force_sign": false,
        "verify_on_read": true
      }
    }
  }
  ```

---

### 命题 I-037：有效信息 = C × SNR

- **形式化**：`effective_info = channel_capacity × signal_to_noise_ratio`
- **直觉**：信息量 = 管道容量 × 信号质量；容量再大，噪声淹没信号也无效
- **AIDS 当前状态**：
  - `aids q` 聚合查询存在，输出较紧凑
  - `pre_tool_use` hook 有 `AIDS_AWARENESS_LINES` 行预算
  - 但无 SNR 感知 — 不知道哪些 trace 是信号、哪些是噪声
- **差距**：无信噪比度量 — 无法区分高价值 trace 和噪声
- **实现建议**（可插拔过滤策略）：
  1. **trace 评分权重**：ratings 影响查询排序权重 — 高评分 trace 优先返回
  2. **SNR 仪表盘**：`aids stats --snr` 显示信号/噪声比（基于 ratings 分布）
  3. **输出压缩策略**：`output.compression` — `["full", "compact", "minimal"]`
     - `full`：返回所有字段
     - `compact`：仅 `traceId + operation + purpose`（当前默认）
     - `minimal`：仅 `count + last_actor`（最低 token）
  4. **相关性过滤**：`query.relevance_filter` 策略 — 按文件距离、时间窗口、评分过滤
- **配置示例**：
  ```json
  {
    "strategies": {
      "snr": {
        "output_compression": "compact",
        "relevance_filter": "time_window",
        "time_window_hours": 24,
        "min_rating": null
      }
    }
  }
  ```

---

### BFS-SNR 方向不变量：SNR 坍塌方向

- **形式化**：若无显式防御，`d(SNR)/dt ≤ 0`（信噪比只降不升）
- **直觉**：不加维护，信号必然被噪声淹没
- **AIDS 当前状态**：
  - 无自动清理机制 — trace 永久累积
  - `aids stats` 可看总量但无衰减
- **差距**：SNR 单调下降无对抗 — 累积的旧 trace 淹没新信号
- **实现建议**（可插拔衰减策略）：
  1. **时间衰减**：`trace.decay` 策略 — 旧 trace 权重按半衰期递减
  2. **评分衰减**：未评分 trace 的默认权重低于已评分 trace
  3. **容量上限**：`trace.max_entries_per_file` — 超出时淘汰低分记录
  4. **所有策略均可关闭** — playground 原则

---

### BFS-forge_cost 不变量：伪造成本递增

- **形式化**：防御迭代后 `forge_cost(t+1) ≥ forge_cost(t)`
- **直觉**：系统应越来越难伪造
- **AIDS 当前状态**：
  - 当前 forge_cost ≈ 0（JSONL 文本）
  - 无升级路径 — 没有"从弱签名升级到强签名"的机制
- **差距**：无递增路径 — 一次配置，无法渐进加强
- **实现建议**：
  1. **签名后端热升级**：`aids config set strategies.signature.backend sqlite_ledger`
     - 系统自动迁移现有 JSONL → SQLite
     - 旧记录保留原始签名，新记录用新后端
  2. **混合模式**：支持同时启用多个后端（如 hash_chain + git_notes）

---

## BFS 五不变量完整映射

| BFS 不变量 | 含义 | AIDS 对应 | 当前满足? | 补强建议 |
|------------|------|-----------|-----------|----------|
| SNR 坍塌方向 | 无防御时信噪比必降 | trace 衰减 + 输出压缩 | 部分 | 添加衰减策略 |
| forge_cost 递增 | 防御迭代提高伪造代价 | 签名后端 | 不满足 | 实现 SignatureBackend 抽象 |
| identity_binding | 身份绑定不可匿名化 | session_id 注入 + `aids current` | 大部分满足 | 签名绑定到 trace |
| ACI 退化 | 评估指标被优化而非目标 | ratings 系统 | 部分 | 评分不可自评 + 审计日志 |
| variety_gap 扩展 | 攻击多样性 > 防御多样性 | hook 覆盖范围 | 不满足 | 可插拔 hook 策略 |

---

## Lean 4 验证定理映射

### T1：selection_pressure_rises

- **条件**：`generation_cost / verification_cost → 0`
- **结论**：选择门槛必须递增
- **AIDS 设计含义**：系统需要可配置的质量门槛，随 agent 数量增长自动收紧

### T2：forge_cost_suppresses_noise

- **条件**：`cheatingPayoff < forgeCost + E[sanction]`
- **结论**：伪造代价足够高时噪声被抑制
- **AIDS 设计含义**：签名后端是核心策略，必须可插拔替换

### T3：forge_cost_preserves_snr

- **条件**：T2 的条件满足
- **结论**：SNR 得到保持
- **AIDS 设计含义**：伪造成本策略直接服务于信噪比维护

---

## 防御设计五原则 → AIDS 实现

### 原则 1：验证迁移到可重放过程

- **Bach 原文**：验证从"看结果"迁移到"重放过程 + 密封环境 + 新鲜任务"
- **AIDS 实现**：
  - `aids op-chain <path>` 已提供操作链重放
  - 待实现：`aids replay <traceId>` — 按操作链重放验证
  - 配置：`verification.replay_enabled: true/false`

### 原则 2：重耦合伪造成本到真实生产成本

- **Bach 原文**：让伪造成本接近真实工作成本
- **AIDS 实现**：
  - 签名后端（见 B-2）使篡改 trace 的成本 ≥ 重做工作
  - 待实现：签名验证失败时标记 trace 为 `tampered`
  - 配置：`signature.tamper_marking: true/false`

### 原则 3：每次写入绑定身份

- **Bach 原文**：every write binds identity
- **AIDS 实现**：
  - `session_id` 注入已覆盖 hooks、CLI、trace
  - 待强化：签名绑定 `session_id + timestamp + file_hash`
  - 自指原则：错误消息、caption、注释均携带身份

### 原则 4：每个控制动作可解释

- **Bach 原文**：every control action explainable
- **AIDS 实现**：
  - `aids why <path>` 查询操作理由（`purpose` 字段）
  - 待实现：`aids explain <traceId>` — 生成人类可读的操作解释
  - 配置：`output.explain_format: ["plain", "json"]`

### 原则 5：攻击多样性 → 防御多样性

- **Bach 原文**：defense variety must match attack variety
- **AIDS 实现**：
  - Hook 系统已覆盖 `pre_tool_use` / `post_tool_use`
  - 待实现：可插拔 hook 策略注册表 — 社区可贡献新防御 hook
  - 配置：`hooks.plugins: ["default", "goodhart_guard", "identity_auditor"]`

---

## 实现优先级

按"低成本高收益"排序：

| 优先级 | 建议 | 对应定理 | 复杂度 |
|--------|------|----------|--------|
| P0 | 签名后端抽象 + hash_chain 实现 | B-2, T2, T3 | 中 |
| P0 | 输出压缩策略（compact/minimal） | I-037 | 低 |
| P1 | SNR 衰减策略 | BFS-SNR | 低 |
| P1 | trace 速率限制策略 | B-1 | 低 |
| P2 | `aids verify` 命令 | B-2 | 中 |
| P2 | 签名后端热升级 | BFS-forge_cost | 中 |
| P3 | `aids replay` 命令 | 防御原则 1 | 高 |
| P3 | 可插拔 hook 注册表 | 防御原则 5 | 高 |

---

## 附录：策略注册表设计

所有策略通过统一接口注册到 `~/.aids/config.json`：

```
strategies/
├── signature/          # 签名后端策略
│   ├── none.py         # 无签名（默认，开发用）
│   ├── hash_chain.py   # hash chain 签名
│   └── sqlite_ledger.py # SQLite 只追加签名
├── filter/             # 查询过滤策略
│   ├── time_window.py  # 按时间窗口过滤
│   ├── relevance.py    # 按相关性评分过滤
│   └── rating_weighted.py # 按评分权重排序
├── decay/              # 衰减策略
│   ├── none.py         # 不衰减（默认）
│   ├── half_life.py    # 半衰期衰减
│   └── capacity.py     # 容量上限淘汰
└── compression/        # 输出压缩策略
    ├── full.py         # 完整输出
    ├── compact.py      # 紧凑输出（默认）
    └── minimal.py      # 最小输出
```

每项策略独立可启用、可替换、可组合。零依赖，Python stdlib only。
