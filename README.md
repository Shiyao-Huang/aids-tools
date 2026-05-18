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

```
📝 config.json
  ← claude-impl-01 · implementer · "修复登录 bug" · 2分钟前
  ← codex-architect · architect · "调整数据库配置" · 15分钟前
  ← bash-human-001 · developer · "手动改了端口号" · 1小时前
```

写之前，AIDS 会**先给你看一眼**有没有人刚动过这个文件（写前必读 / 写前读毒）：

> ⚠️ 注意！codex-architect 15分钟前刚改了这个文件，目的是"调整数据库配置"。你确定还要改吗？

**差点撞车的小工们，现在能看到彼此的脚印了。**

### 3. ⭐ 评价贴（Rating）

有人干得好？贴好评。有人搞破坏？贴差评。

```bash
aids rate trace_003 bad "不该在生产配置里用 test 密码"
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

验证：`aids doctor` 全绿就 OK。

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
📝 README.md
  ← bash-human-001 · developer · "修了个 typo" · 刚刚
  ← claude-scribe · scribe · "写小孩版 README" · 5分钟前
  ← codex-impl-01 · implementer · "加了个 banner" · 1小时前
```

**人类也是小工之一，名字贴对所有人一视同仁。**

### 🎬 场景三：K 的敌敌畏被差评

```bash
$ aids rate trace_042 bad "直接 rm -rf /tmp/important 太危险了"

# 下一个人来的时候
[claude-impl-02] 准备写 /tmp/important/config.yaml →
  AIDS 警告：⚠️ 此区域有 1 个差评操作："直接 rm -rf /tmp/important 太危险了"
[claude-impl-02] 额...我换个地方吧
```

**差评不是惩罚，是信号。让后来的人少踩坑。**

### 🎬 场景四：监控回放

```bash
$ aids timeline README.md
Claude(scribe) → Codex(impl) → Bash(human) → Claude(architect) → Codex(impl)

# 像监控摄像头回放一样，每个小工什么时候来过，干了什么，一目了然
```

**这不是追溯。追溯只是副产品。真正发生的是：每个小工长脑子了。它知道周围有谁，谁干了什么，什么该碰什么不该碰。**

---

## 怎么做到的？

AIDS 的核心就是三个东西：

1. **Hook**：在 Claude Code / Codex / Bash 每次操作前后注入"看看有没有人刚动过"的逻辑
2. **Timeline**：所有操作写入 `~/.aids/timeline/*.jsonl`，统一的操作链
3. **Rating**：任何人可以给操作贴好评/差评，后来者能看到

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
