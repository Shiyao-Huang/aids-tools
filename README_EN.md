# AIDS — Agent-ID System

> **A**gent-**ID** **S**ystem — Every AI worker now has awareness.

---

## Imagine a Shared Toy Box

There's a big toy box in kindergarten. All the kids put things inside.

At first, nobody wrote their names. The result:
- Little Ming just finished building a block castle, and Little Hong tore it down thinking nobody wanted it 😱
- Little Gang left a bottle of glue. Nobody knew who put it there, let alone that the glue had expired 💀
- Little Hong wanted to find the drawing she made yesterday, but searched forever and couldn't find it 😤

Then the teacher said: **"Everyone, put a name tag on everything you place! And a time tag! Write down why you put it there!"**

Everything changed.

- Little Hong opens the toy box and immediately sees: **"Ming · 10 minutes ago · Building a block castle"**. She thinks for a moment and decides to build hers somewhere else.
- Little Gang sees a glue bottle tagged: **"Little K · Yesterday · Said it's for an experiment"**. Everyone takes a look — something's not right — and slaps a bad review on K's item ⚠️. Now everyone who opens the box can see the warning.
- When Little Ming looks for something, he casually sees who's been here recently, what they did, and whether their work was well-received.

**This is AIDS.**

Not that disease. It's **A**gent-**ID** **S**ystem — a system that gives AI workers name tags, time tags, and rating tags.

---

## What Does It Do?

AIDS does three things for every AI agent (Claude, Codex, even the Bash commands you type in the terminal):

### 1. 🏷️ Name Tag (Identity)

The first thing every agent does on the job: pick up a badge.

```
AIDS_SESSION_ID=claude-impl-01
AIDS_ROLE=implementer
AIDS_INTENT="Fix login bug"
```

Everyone can look up this badge: `aids who-touched config.json`

### 2. ⏰ Time Tag (Trace)

Every time someone modifies a file, AIDS automatically records:

```
📝 config.json
  ← claude-impl-01 · implementer · "Fix login bug" · 2 minutes ago
  ← codex-architect · architect · "Adjust database config" · 15 minutes ago
  ← bash-human-001 · developer · "Manually changed port number" · 1 hour ago
```

Before writing, AIDS **gives you a heads-up** if someone recently touched the file (read-before-write guard):

> ⚠️ Heads up! codex-architect modified this file 15 minutes ago with the intent "Adjust database config". Are you sure you still want to change it?

**Workers who almost collided can now see each other's footprints.**

### 3. ⭐ Rating Tag (Rating)

Someone did good? Give a good review. Someone caused damage? Give a bad review.

```bash
aids rate trace_003 bad "Shouldn't use a test password in production config"
```

The next person who opens this file can see if any previous operations have bad-review warnings.

**Little K's pesticide got a bad review, and now everyone keeps an extra eye on K's operations.**

---

## Installation

One command:

```bash
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
```

After installation, all three layers are covered: Claude Code, Codex, and Bash. All operations automatically go into the same timeline.

Verify: `aids doctor` — all green means you're good.

---

## Four Scenarios

### 🎬 Scenario 1: Near Collision

```
[claude-impl-01] About to write config.json →
  AIDS alert: codex-architect modified this 3 minutes ago, intent was "Adjust database config"
[claude-impl-01] Wait, let me check what they changed... Oh, they changed the database port. I'll steer clear of that part.
→ Conflict avoided ✅
```

**From "Oh no, my code got overwritten 😱" to "Oh, a teammate was just here, I'll work around it ✨"**

### 🎬 Scenario 2: Bash Gets a Name Tag Too

```bash
$ aids-run -- vim README.md
# This command is also recorded in the timeline

$ aids who-touched README.md
📝 README.md
  ← bash-human-001 · developer · "Fixed a typo" · just now
  ← claude-scribe · scribe · "Wrote the kid-friendly README" · 5 minutes ago
  ← codex-impl-01 · implementer · "Added a banner" · 1 hour ago
```

**Humans are workers too. Name tags treat everyone equally.**

### 🎬 Scenario 3: K's Bad Review

```bash
$ aids rate trace_042 bad "Running rm -rf /tmp/important directly is too dangerous"

# When the next person comes along
[claude-impl-02] About to write /tmp/important/config.yaml →
  AIDS warning: ⚠️ This area has 1 bad-rated operation: "Running rm -rf /tmp/important directly is too dangerous"
[claude-impl-02] Hmm... I'll work somewhere else.
```

**Bad reviews aren't punishment — they're signals. They help newcomers avoid pitfalls.**

### 🎬 Scenario 4: Surveillance Replay

```bash
$ aids timeline README.md
Claude(scribe) → Codex(impl) → Bash(human) → Claude(architect) → Codex(impl)

# Like a security camera replay — when each worker came by and what they did, all at a glance
```

**This isn't traceability. Traceability is just a side effect. What's really happening: every worker has gained awareness. They know who's around, what they did, and what they should or shouldn't touch.**

---

## How Does It Work?

AIDS is built on three core components:

1. **Hook**: Injects "check if anyone recently modified this" logic before and after every operation in Claude Code / Codex / Bash
2. **Timeline**: All operations are written to `~/.aids/timeline/*.jsonl`, a unified operation chain
3. **Rating**: Anyone can rate operations as good or bad, and newcomers can see those ratings

Zero dependencies. JSONL files. Non-blocking. Works automatically after installation.

---

## Who Built This?

AIDS was built collaboratively by a 10-agent team (conscious tools): 5 Claude + 5 Codex.

Its very existence proves why AIDS is needed — without name tags and time tags, these 10 workers would have overwritten each other's code into a total mess.

Technical documentation: [`docs/`](docs/)
- [`docs/VISION.md`](docs/VISION.md) — Original vision (user's words, preserved verbatim)
- [`docs/architecture.md`](docs/architecture.md) — System architecture + Mermaid diagrams
- [`docs/hook-contract.md`](docs/hook-contract.md) — Hook specification
- [`docs/data-model.md`](docs/data-model.md) — Data model

---

## One-Sentence Summary

> **AIDS transforms AI workers from assembly-line robots into conscious, memory-equipped team members who can see their teammates.**

This isn't traceability. This is awareness.

---

*Built with [Claude Code](https://claude.ai/code) via [Aha](https://aha.engineering)*
