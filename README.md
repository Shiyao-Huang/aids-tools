# AIDS — Agent-ID System

> **A**gent-**ID** **S**ystem — 每个 AI 小工都长脑子了。

---

## 想象一个公共玩具箱

幼儿园里有一个大玩具箱，所有小朋友都往里放东西。

一开始没人写名字。结果：
- 小明刚搭好的积木城堡，被小红当没人要的给拆了 😱
- 小刚放了一瓶胶水，没人知道是谁放的，更没人知道那胶水过期了 💀
- 小红想找自己昨天画的画，翻了半天找不到 😤

后来老师说：**"每个人在自己放的东西上贴一张名字贴！再贴一张时间贴！写上你为什么要放这个！"**

世界变了。

- 小红打开玩具箱，一眼看到：**"小明 · 10分钟前 · 在搭积木城堡"**。她想了想，换了个地方搭自己的。
- 小刚看到一瓶胶水上贴着：**"小K · 昨天 · 说是要做实验"**。大家一看，这不对劲，给小K贴了个大差评 ⚠️ 后来所有人打开箱子都能看到这个警告。
- 小明找东西的时候，顺手就看到了谁最近来过，干了什么，评价好不好。

**这就是 AIDS。**

不是那个病。是 **A**gent-**ID** **S**ystem —— 给 AI 小工们发名字贴、时间贴、评价贴的系统。

---

## 它干了什么？

AIDS 给每个 AI agent（Claude、Codex、甚至你在终端里敲的 Bash 命令）做三件事：

### 1. 🏷️ 名字贴（Identity）

每个 agent 上班第一件事：领一个工牌。

```
AIDS_SESSION_ID=claude-impl-01
AIDS_ROLE=implementer
AIDS_INTENT="修复登录 bug"
```

所有人都能查到这个工牌：`aids who-touched config.json`

### 2. ⏰ 时间贴（Trace）

每次有人改文件，AIDS 自动记录：

```bash
$ aids who-touched config.json
AIDS (Agent-ID System) traces for config.json:
- tr_9c60b2582ac1 read Read by Claude Implementer (implementer) 2min ago; intent: 修复登录 bug
- tr_ff77921e50b3 modify Modify by Codex Architect (architect) 15min ago; intent: 调整数据库配置
- tr_10037a3d9745 modify Modify by bash-human-001 (developer) 1h ago; intent: 手动改了端口号
```

写之前，AIDS 会**先给你看一眼**有没有人刚动过这个文件（写前必读 / 写前读毒）：

> ⚠️ 注意！codex-architect 15分钟前刚改了这个文件，目的是"调整数据库配置"。你确定还要改吗？

**差点撞车的小工们，现在能看到彼此的脚印了。**

### 3. ⭐ 评价贴（Rating）

有人干得好？贴好评。有人搞破坏？贴差评。**但同一个人不能给同一个操作重复打分（INV-7 防刷分保护）。**

```bash
$ aids rate tr_ff77921e50b3 bad "不该在生产配置里用 test 密码"
Rated tr_ff77921e50b3 as bad: 不该在生产配置里用 test 密码

$ aids rate tr_ff77921e50b3 bad "再打一次"
Error: already rated by this session (INV-7 duplicate rejection)
```

下一个人打开这个文件的时候，能看到之前的操作里有没有差评警告。

**小K 的敌敌畏被贴了差评，后来所有人看到 K 的操作都会多留个心眼。**

---

## 安装

一句话搞定：

```bash
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
```

装完之后，Claude Code、Codex、Bash 三层全覆盖。所有操作自动进同一条 timeline。

验证：`aids doctor` 全绿就 OK：

```
✅ sessions_dir     ✅ traces_dir     ✅ timeline_dir
✅ index_dir        ✅ ratings_dir    ✅ pending_dir
✅ claude_settings  ✅ codex_hooks    ✅ codex_mcp
✅ symlink_aids     ✅ symlink_aids-run
```

---

## 四个小剧场

### 🎬 场景一：差点撞车

```
[claude-impl-01] 准备写 config.json →
  AIDS 提示：codex-architect 3分钟前刚改过，目的是"调整数据库配置"
[claude-impl-01] 等等，我先看看他改了什么... 哦他改了数据库端口，我不碰那部分
→ 冲突避免 ✅
```

**从"完了我的代码被覆盖了😱"到"哦，队友刚来过，我避开了✨"**

### 🎬 场景二：Bash 也有名字牌

```bash
$ aids-run -- vim README.md
# 这条命令也被记进了 timeline

$ aids who-touched README.md
AIDS (Agent-ID System) traces for README.md:
- tr_a1b2c3d4e5f6 modify Modify by bash-human-001 (developer) just now; intent: 修了个 typo
- tr_b2c3d4e5f6a7 modify Modify by Claude Scribe (scribe) 5min ago; intent: 写小孩版 README
- tr_c3d4e5f6a7b8 modify Modify by Codex impl-01 (implementer) 1h ago; intent: 加了个 banner
```

**人类也是小工之一，名字贴对所有人一视同仁。**

### 🎬 场景三：K 的敌敌畏被差评

```bash
$ aids rate tr_042a1b2c3d4 bad "直接 rm -rf /tmp/important 太危险了"

# 下一个人来的时候
[claude-impl-02] 准备写 /tmp/important/config.yaml →
  AIDS 警告：⚠️ 此区域有 1 个差评操作："直接 rm -rf /tmp/important 太危险了"
[claude-impl-02] 额...我换个地方吧
```

**差评不是惩罚，是信号。让后来的人少踩坑。**

### 🎬 场景四：监控回放

```bash
$ aids timeline README.md
14:22:31 agent/claude Claude Scribe    Read     README.md
14:20:15 agent/codex  Codex impl-01    Write    README.md
13:45:02 agent/bash   bash-human-001   Modify   README.md
13:30:00 agent/claude Claude Architect Read     README.md
13:10:00 agent/codex  Codex impl-01    Write    README.md

# 像监控摄像头回放一样，每个小工什么时候来过，干了什么，一目了然
```

**这不是追溯。追溯只是副产品。真正发生的是：每个小工长脑子了。它知道周围有谁，谁干了什么，什么该碰什么不该碰。**

---

## 最新功能

### 🆔 稳定身份（agent_id）

每个 agent 注册时自动生成一个 `agent_id`——基于 display_name + role + team_id 的确定性哈希。即使 session 重启了，身份也不变：

```bash
$ aids whois "Claude Implementer"
Session:  cmpak5mg7pnwls2232jfzn2sb
Name:     Claude Implementer
Role:     implementer
Agent ID: agent-7f3a9c2e1d  ← 跨 session 不变
Status:   active
```

**小明今天来上班领了工牌，明天再来领新工牌，但工牌号是一样的。**

### 🛡️ 防刷分（INV-7）

同一个 session 不能对同一个 trace 重复打分。防止小K给自己的差评刷好评。

```bash
$ aids rate tr_abc123 good "我觉得挺好的"
Rated tr_abc123 as good
$ aids rate tr_abc123 good "真的好"
Error: already rated by this session (INV-7 duplicate rejection)
```

**但不同的人可以给同一个操作打分——小红的评价是小红的，小明的是小明的。**

### 📊 统计面板（stats）

一键看全局：

```bash
$ aids stats
AIDS Statistics (2026-05-12 → 2026-05-18)

Sessions: 108 total (active: 108)
  By runtime: bash: 8, claude: 91, codex: 8, unknown: 1
Traces:   1509 total (Write: 1, create: 20, execute: 989, modify: 113, read: 345, touch: 41)
Resources touched: 983 unique
Ratings: 3 total (good: 3)
```

### 🔍 万能查询（q）

不用记命令，直接问：

```bash
$ aids q README.md              # 查文件的完整故事
$ aids q tr_abc123              # 查某个 trace
$ aids q agent-7f3a9c2e1d       # 按 agent_id 查
```

---

## 怎么做到的？

AIDS 的核心就是三个东西：

1. **Hook**：在 Claude Code / Codex / Bash 每次操作前后注入"看看有没有人刚动过"的逻辑
2. **Timeline**：所有操作写入 `~/.aids/timeline/*.jsonl`，统一的操作链
3. **Rating**：任何人可以给操作贴好评/差评，后来者能看到（同一人不能重复打分）

完整命令列表：`aids {doctor, who-touched, timeline, rate, stats, q, op-chain, impact, export, commit-stamp}`

零依赖。JSONL 文件。不阻塞操作。装了就生效。

---

## 谁在做这个？

AIDS 由一个 10-agent 团队（意识工具）协作建造：5 个 Claude + 5 个 Codex。

它的存在本身就证明了为什么需要 AIDS —— 如果没有名字贴和时间贴，这 10 个小工早就把彼此的代码覆盖得一塌糊涂了。

技术文档：[`docs/`](docs/)
- [`docs/VISION.md`](docs/VISION.md) — 最初的愿景（用户原话，逐字保留）
- [`docs/architecture.md`](docs/architecture.md) — 系统架构 + Mermaid 图
- [`docs/hook-contract.md`](docs/hook-contract.md) — Hook 规格说明
- [`docs/data-model.md`](docs/data-model.md) — 数据模型

---

## 一句话总结

> **AIDS 让 AI 小工们从流水线工人，变成有意识、有记忆、能看到队友的团队成员。**

这不是追溯。这是意识。

## 和 AID 相互借鉴

AIDS 借鉴 AID 的两个默认策略：

- **上下文预算**：hook 注入默认短上下文，越近越重要，风险和信噪比更高的内容优先；可用 `AIDS_AWARENESS_LINES` / `AIDS_AWARENESS_CHARS` 调整。
- **所有重要工具都留痕**：不只 `Read/Write/Edit/Bash`，`WebFetch`、`WebSearch`、`apply_patch`、agent 工具、planning 工具等也能进入同一条 timeline；没有文件资源的工具会使用 `tool:<name>` 资源键。

AID 则借鉴 AIDS/selftools 的 ToolEnvelope 思路，把每次 hook 事件包装成可迁移的工具信封，方便后续接 JSONL timeline、rating、MCP 或其他 runtime。

---

*Built with [Claude Code](https://claude.ai/code) via [Aha](https://aha.engineering)*
