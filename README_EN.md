# AIDS — Agent-ID System

> **A**gent-**ID** **S**ystem — Every AI worker now has awareness.

---

## Quick Install

```bash
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
```

One line. Claude Code + Codex + Bash coverage, all automatic. Verify: `aids doctor`

<details>
<summary>More install options</summary>

**From source:**
```bash
git clone https://github.com/Shiyao-Huang/aids-tools.git
cd aids-tools && ./install.sh --source .
```

**Custom path:**
```bash
AIDS_HOME=~/.my-aids curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
```

**Uninstall:**
```bash
~/.aids/selftools/install.sh --uninstall        # keep data
~/.aids/selftools/install.sh --uninstall --purge-data  # remove everything
```

</details>

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

```bash
$ aids who-touched config.json
AIDS (Agent-ID System) traces for config.json:
- tr_9c60b2582ac1 read Read by Claude Implementer (implementer) 2min ago; intent: Fix login bug
- tr_ff77921e50b3 modify Modify by Codex Architect (architect) 15min ago; intent: Adjust database config
- tr_10037a3d9745 modify Modify by bash-human-001 (developer) 1h ago; intent: Manually changed port number
```

Before writing, AIDS **gives you a heads-up** if someone recently touched the file (read-before-write guard):

> ⚠️ Heads up! codex-architect modified this file 15 minutes ago with the intent "Adjust database config". Are you sure you still want to change it?

**Workers who almost collided can now see each other's footprints.**

### 3. ⭐ Rating Tag (Rating)

Someone did good? Give a good review. Someone caused damage? Give a bad review. **But the same person can't rate the same trace twice (INV-7 anti-gaming protection).**

```bash
$ aids rate tr_ff77921e50b3 bad "Shouldn't use a test password in production config"
Rated tr_ff77921e50b3 as bad: Shouldn't use a test password in production config

$ aids rate tr_ff77921e50b3 bad "Rating again"
Error: already rated by this session (INV-7 duplicate rejection)
```

The next person who opens this file can see if any previous operations have bad-review warnings.

**Little K's pesticide got a bad review, and now everyone keeps an extra eye on K's operations.**

---

## Installation Details

> For the quick one-liner, see [Quick Install](#quick-install) at the top. Below are full options.

### Verify Installation

```bash
aids doctor
```

All green means you're good:

```
✅ sessions_dir     ✅ traces_dir     ✅ timeline_dir
✅ index_dir        ✅ ratings_dir    ✅ pending_dir
✅ locks_dir        ✅ config_json
✅ claude_hooks     ✅ codex_hooks    ✅ codex_mcp
✅ symlink_aids     ✅ symlink_aids-mcp  ✅ symlink_aids-run
✅ lock_mechanism   ✅ stale_locks
```

### Install Options

| Option | Description |
|--------|-------------|
| `--source DIR` | Install from a cloned directory, skip git clone |
| `--repo URL` | Specify Git repository URL |
| `--install-dir DIR` | Installation directory (default `~/.aids/selftools`) |
| `--data-dir DIR` | Data directory (default `~/.aids`) |
| `--bin-dir DIR` | Symlink directory (default `~/.local/bin`) |
| `--no-claude` | Skip Claude Code hook registration |
| `--no-codex` | Skip Codex hook registration |
| `--no-mcp` | Skip MCP wrapper registration |
| `--with-gitnexus` | Enable GitNexus code graph awareness |
| `--dry-run` | Preview mode — print only, don't execute |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AIDS_HOME` | `~/.aids` | Data root directory |
| `AIDS_INSTALL_DIR` | `~/.aids/selftools` | Installation directory |
| `AIDS_BIN_DIR` | `~/.local/bin` | Executable directory |
| `AIDS_REPO` | `Shiyao-Huang/aids-tools` | Git repository |
| `CLAUDE_HOME` | `~/.claude` | Claude Code config directory |
| `CODEX_HOME` | `~/.codex` | Codex config directory |

### Post-Install Checklist

```bash
which aids          # → ~/.local/bin/aids
aids doctor         # → all green
aids register-session
aids list-sessions
aids q README.md
```

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
AIDS (Agent-ID System) traces for README.md:
- tr_a1b2c3d4e5f6 modify Modify by bash-human-001 (developer) just now; intent: Fixed a typo
- tr_b2c3d4e5f6a7 modify Modify by Claude Scribe (scribe) 5min ago; intent: Wrote the kid-friendly README
- tr_c3d4e5f6a7b8 modify Modify by Codex impl-01 (implementer) 1h ago; intent: Added a banner
```

**Humans are workers too. Name tags treat everyone equally.**

### 🎬 Scenario 3: K's Bad Review

```bash
$ aids rate tr_042a1b2c3d4 bad "Running rm -rf /tmp/important directly is too dangerous"

# When the next person comes along
[claude-impl-02] About to write /tmp/important/config.yaml →
  AIDS warning: ⚠️ This area has 1 bad-rated operation: "Running rm -rf /tmp/important directly is too dangerous"
[claude-impl-02] Hmm... I'll work somewhere else.
```

**Bad reviews aren't punishment — they're signals. They help newcomers avoid pitfalls.**

### 🎬 Scenario 4: Surveillance Replay

```bash
$ aids timeline README.md
14:22:31 agent/claude Claude Scribe    Read     README.md
14:20:15 agent/codex  Codex impl-01    Write    README.md
13:45:02 agent/bash   bash-human-001   Modify   README.md
13:30:00 agent/claude Claude Architect Read     README.md
13:10:00 agent/codex  Codex impl-01    Write    README.md

# Like a security camera replay — when each worker came by and what they did, all at a glance
```

**This isn't traceability. Traceability is just a side effect. What's really happening: every worker has gained awareness. They know who's around, what they did, and what they should or shouldn't touch.**

---

## Latest Features

### 🆔 Stable Identity (agent_id)

Every agent automatically gets an `agent_id` on registration — a deterministic hash of display_name + role + team_id. Even if the session restarts, the identity stays the same:

```bash
$ aids whois "Claude Implementer"
Session:  cmpak5mg7pnwls2232jfzn2sb
Name:     Claude Implementer
Role:     implementer
Agent ID: agent-7f3a9c2e1d  ← stable across sessions
Status:   active
```

**Ming picks up a badge today. He gets a new badge tomorrow. But the badge number is always the same.**

### 🛡️ Anti-Gaming (INV-7)

The same session can't rate the same trace twice. Prevents Little K from gaming his own bad reviews.

```bash
$ aids rate tr_abc123 good "I think it's fine"
Rated tr_abc123 as good
$ aids rate tr_abc123 good "Really good"
Error: already rated by this session (INV-7 duplicate rejection)
```

**But different people can rate the same operation — Hong's review is Hong's, Ming's is Ming's.**

### 📊 Stats Dashboard (stats)

One command to see the big picture:

```bash
$ aids stats
AIDS Statistics (2026-05-12 → 2026-05-18)

Sessions: 108 total (active: 108)
  By runtime: bash: 8, claude: 91, codex: 8, unknown: 1
Traces:   1509 total (Write: 1, create: 20, execute: 989, modify: 113, read: 345, touch: 41)
Resources touched: 983 unique
Ratings: 3 total (good: 3)
```

### 🔌 Session-Start Identity Inference

When a session starts (Claude Code, Codex, or Bash), AIDS automatically infers the agent's identity from environment variables — no manual registration needed:

```bash
# Auto-inferred on session-start hook:
# - session_id ← AIDS_SESSION_ID (or AHA_SESSION_ID fallback chain)
# - role       ← AIDS_ROLE / AHA_AGENT_ROLE / ROLE
# - runtime    ← AIDS_RUNTIME or detected from transcript_path (.claude / .codex)
# - display    ← AIDS_DISPLAY_NAME / AHA_SESSION_NAME
# - goal       ← AIDS_INTENT / AHA_INTENT
# - agent_id   ← deterministic hash(display_name + role + team_id), stable across restarts
```

The hook also writes three self-reference files:
- `~/.aids/.identity` — plain-text quick-read of current session
- `~/.aids/sessions/.current` — symlink to active session JSON
- `.claude/AIDS_IDENTITY.md` — injected into Claude's context window

**No setup needed. Just start working, and AIDS figures out who you are.**

### 📡 Hook Output Contract

AIDS hooks output a dual-format JSON that both Claude Code and Codex can consume:

```json
{
  "systemMessage": "AIDS awareness for Write:\nYou are ... about to write.\n...",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "AIDS awareness for Write:\n..."
  }
}
```

- `systemMessage`: Human-readable context injected into the agent's awareness
- `hookSpecificOutput`: Structured hook event with `hookEventName` + `additionalContext`
- Works for `SessionStart`, `PreToolUse`, and `PostToolUse` events

This dual format ensures compatibility across runtimes without runtime-specific code paths.

### 💥 Impact Analysis (impact)

See the full blast radius of changing a file — which sessions touched it, what they did, and the code graph dependencies:

```bash
$ aids impact config.json
File Impact Analysis: config.json
  Importance: HIGH
  Risk:       HIGH RISK: 5 files depend on this. Changes have broad impact.
  Agents:     3 unique session(s) touched this file

  Modified by (3 agents):
    Claude Architect (architect/claude) agent_id=agent-a1b2c3d4e5f6
      operations: modify:2, read:1 (3 total)
    Codex Impl #1 (implementer/codex) agent_id=agent-7f8a9b0c1d2e
      operations: modify:1 (1 total)
    bash-human (developer/bash) agent_id=agent-3a4b5c6d7e8f
      operations: read:2 (2 total)

  Dependents (5 files that import/reference this file):
    - src/server.py
    - src/config_loader.py
    - tests/test_config.py
    ...
```

**Before you change a file, know who else depends on it — and who's been here recently.**

### 🔗 Operation Chain (Hash Chain)

Every trace carries a `chain_hash` — SHA256 of the previous hash + current trace's key fields. This forms a tamper-proof chain:

```
GENESIS → tr_a1b2 (chain_hash: a3f8...) → tr_a1b3 (chain_hash: 7e2c...) → ...
```

Tamper with any entry, and all subsequent hashes break.

Verify with `aids verify`:

```bash
$ aids verify                   # Verify integrity of all traces
✅ tr_a1b2c3: chain hash verified
✅ tr_d4e5f6: chain hash verified
✅ tr_7a8b9c: chain hash verified
3 traces checked, 3 valid, 0 tampered.

$ aids verify tr_d4e5f6         # Verify a specific trace
✅ tr_d4e5f6: chain hash verified
```

If someone secretly modified a trace:

```bash
$ aids verify
✅ tr_a1b2c3: chain hash verified
❌ tr_d4e5f6: chain_hash mismatch: trace was tampered or chain broken
✅ tr_7a8b9c: chain hash verified
3 traces checked, 2 valid, 1 tampered.
```

**Name tags in the toy box are sealed with transparent tape — they can't be peeled off.**

### 🛡️ Protected Config (Protected Keys)

Some config keys are security-critical (e.g., hash chain signing strategy). Agents cannot override them:

```python
# These keys are immune to config.json overrides
PROTECTED_CONFIG_KEYS = {
    "signature.enabled": True,         # Signing cannot be disabled
    "signature.strategy": "hash_chain", # Strategy cannot be changed
    "impact.enabled": True,            # Impact analysis cannot be disabled
}
```

**The teacher said "name tags are mandatory" — it's a class rule, not a suggestion.**

### 📖 Bash Read-Operation Detection

Previously only write operations were tracked. Now 20+ read commands like `cat`, `grep`, `head`, `tail`, `wc`, `sort`, `awk`, `sed`, `diff` also leave traces:

```bash
# Agent ran: cat config.json | grep database
$ aids who-touched config.json
AIDS (Agent-ID System) who-touched: config.json
───────────────────────────────────────────
│ tr_a1b2c3 read cat by Claude Impl #1 (implementer) 2min ago
│ tr_d4e5f6 modify Edit by Codex Architect (architect) 15min ago
```

**Not just "who changed it" — now even "who read it" is tracked.**

### 🌈 Colored who-touched Output

Terminal `who-touched` now uses color — different roles get different colors, operation types have symbol indicators:

```
╭──────────────────────────────────────╮
│ AIDS who-touched: config.json        │
├──────────────────────────────────────┤
│ tr_a1b2 ✎ Write by Claude Impl (implementer) 2min ago
│ tr_d4e5 ✎ Edit by Codex Architect (architect) 15min ago
│ tr_7a8b 👁 Read by bash-human (developer) 1h ago
╰──────────────────────────────────────╯
  3 traces  |  3 distinct agents
```

Supports `--sort time|role|op` ordering. Respects `NO_COLOR` environment variable.

### 🔍 Universal Query (q)

Don't memorize commands — just ask:

```bash
$ aids q README.md              # Full story of a file
$ aids q tr_abc123              # Look up a specific trace
$ aids q agent-7f3a9c2e1d       # Query by agent_id
```

---

## How Does It Work?

AIDS is built on four core components:

1. **Hook**: Injects "check if anyone recently modified this" logic before and after every operation in Claude Code / Codex / Bash
2. **Timeline**: All operations are written to `~/.aids/timeline/*.jsonl`, a unified operation chain
3. **Hash Chain**: Each trace's chain_hash links to the previous one, forming a tamper-proof signature chain
4. **Rating**: Anyone can rate operations as good or bad, and newcomers can see those ratings (no duplicate ratings per session)

Full command list: `aids {doctor, verify, who-touched, timeline, rate, stats, q, op-chain, impact, export, commit-stamp}`

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

## Cross-Pollination with AID

AIDS borrows two default strategies from AID:

- **Context budget**: Hooks inject short context by default — more recent entries first, prioritizing risk and signal-to-noise ratio; configurable via `AIDS_AWARENESS_LINES` / `AIDS_AWARENESS_CHARS`.
- **All important tools leave traces**: Not just `Read/Write/Edit/Bash` — `WebFetch`, `WebSearch`, `apply_patch`, agent tools, and planning tools also enter the same timeline; tools without file resources use `tool:<name>` resource keys.

AID in turn borrows the ToolEnvelope concept from AIDS/selftools, wrapping each hook event into a portable tool envelope for future integration with JSONL timeline, rating, MCP, or other runtimes.
