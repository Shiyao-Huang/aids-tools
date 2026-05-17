# AIDS (Agent-ID System) — Architecture

> "世界需要自指，环境需要自指，工具也需要自指。"
> The world needs self-reference. The environment needs self-reference. Tools need self-reference too.

**AIDS** = **A**gent-**ID** **S**ystem — every agent gets an ID, every operation leaves a trace.

## Overview

AIDS (Agent-ID System) is a **transparent wrapper layer** that sits between Claude Code / Codex CLIs and their native tools (Write, Read, Edit, Bash). Every tool call leaves a labeled trace — who called it, why, on what resource. When the next agent opens the same file, they see the cabinet contents and every label left by their teammates.

This is not middleware for coordination. It is **ambient awareness** — agents discover each other through the traces of their work, like colleagues sharing a workshop where every tool leaves a mark.

**Install**: One line. `curl -sfL https://raw.githubusercontent.com/.../install.sh | bash` — works for both Claude Code and Codex.

---

## System Architecture

```mermaid
graph TB
    subgraph CLIs["Agent Runtimes"]
        CC["Claude Code\n(claude CLI)"]
        CX["Codex\n(codex CLI)"]
    end

    subgraph HookLayer["Hook Chain Layer"]
        direction TB
        PRE["PreToolUse Hook\npre_tool_use.sh"]
        POST["PostToolUse Hook\npost_tool_use.sh"]
    end

    subgraph ToolLayer["Native Tool Layer"]
        W["Write"]
        R["Read"]
        E["Edit"]
        B["Bash"]
    end

    subgraph Core["AIDS Core"]
        direction TB
        SR["Session Registry\n~/.aids/sessions/"]
        TS["Trace Store\n~/.aids/traces/"]
        RL["Rating Layer\n~/.aids/ratings/"]
        IDX["Resource Index\n~/.aids/index/"]
    end

    subgraph QueryAPI["Query Interface"]
        QR["who-touched? <path>"]
        QS["session-info <id>"]
        QC["op-chain <path>"]
    end

    CC -->|"tool call JSON"| PRE
    CX -->|"tool call JSON"| PRE
    PRE -->|"injects trace context\ninto tool call"| ToolLayer
    ToolLayer -->|"tool result"| POST
    POST -->|"records operation"| TS
    POST -->|"updates index"| IDX
    PRE -->|"reads last N ops"| IDX
    PRE -->|"resolves session"| SR
    CC -->|"session.start"| SR
    CX -->|"session.start"| SR
    RL -->|"annotates"| TS
    QueryAPI -->|"reads"| Core
    IDX -->|"fast path lookup"| TS

    style Core fill:#1a1a2e,color:#eee
    style HookLayer fill:#16213e,color:#eee
    style CLIs fill:#0f3460,color:#eee
    style ToolLayer fill:#533483,color:#eee
```

---

## Hook Chain Detail

```mermaid
sequenceDiagram
    participant A as Agent (Claude/Codex)
    participant PRE as PreToolUse Hook
    participant SR as Session Registry
    participant IDX as Resource Index
    participant TS as Trace Store
    participant TOOL as Native Tool
    participant POST as PostToolUse Hook

    A->>PRE: {session_id, tool, input}
    PRE->>SR: resolve(session_id) → {role, goal, task_id}
    PRE->>IDX: last_ops(resource_path, limit=5)
    IDX-->>PRE: [TraceRecord...]
    Note over PRE: Build context injection:<br/>"Last writer: Jane@scribe<br/>Goal: document API<br/>2m ago"
    PRE-->>A: inject context into tool env
    A->>TOOL: execute(tool_call)
    TOOL-->>POST: {result, exit_code, duration_ms}
    POST->>TS: write(TraceRecord)
    POST->>IDX: update(resource_path, trace_id)
    POST-->>A: {result + trace_id}
    Note over A: Agent now aware of<br/>trace_id for this op
```

---

## Session Registry

```mermaid
graph LR
    subgraph Registry["Session Registry (~/.aids/sessions/)"]
        S1["session_abc123.json\nrole: architect\ngoal: design architecture\ntask: RJB41asLxowC"]
        S2["session_def456.json\nrole: scribe\ngoal: document AIM\ntask: RJB41asLxowC"]
        S3["session_ghi789.json\nrole: builder\ngoal: implement hooks\ntask: null"]
    end

    subgraph Lookup["Query"]
        Q1["who is cmp9zfs21...?"]
        Q2["what is their goal?"]
    end

    Q1 -->|"resolve"| Registry
    Q2 -->|"resolve"| Registry
    S1 -.->|"readable by all"| Q1
```

---

## Trace Storage & Resource Index

```mermaid
graph TB
    subgraph TraceStore["Trace Store (~/.aids/traces/YYYY-MM-DD.jsonl)"]
        T1["trace_001: Write docs/arch.md\n  by: architect/abc123\n  intent: design doc\n  pre_hash: null\n  post_hash: a3f9..."]
        T2["trace_002: Read docs/arch.md\n  by: scribe/def456\n  intent: document AIM\n  pre_hash: a3f9..."]
        T3["trace_003: Edit docs/arch.md\n  by: scribe/def456\n  intent: add data model\n  pre_hash: a3f9...\n  post_hash: b7c2..."]
    end

    subgraph Index["Resource Index (~/.aids/index/)"]
        I1["docs/arch.md → [001, 002, 003]"]
        I2["aids/hooks/pre.sh → [004, 005]"]
    end

    subgraph RatingLayer["Rating Layer (~/.aids/ratings/)"]
        R1["rating_001: trace_003\n  rater: builder/ghi789\n  score: bad\n  comment: arch doc\n  missing data model"]
        R2["rating_002: trace_001\n  rater: scribe/def456\n  score: good\n  comment: clear structure"]
    end

    TraceStore -->|"indexed by resource"| Index
    RatingLayer -->|"annotates"| TraceStore
```

---

## Installation Architecture

```mermaid
graph TB
    subgraph Install["One-Liner Install"]
        CURL["curl -sfL install.sh | bash"]
    end

    subgraph Steps["Install Steps"]
        S1["1. Detect runtime\n(claude / codex / both)"]
        S2["2. Write hook scripts\n~/.aids/hooks/"]
        S3["3. Patch settings.json\n(Claude Code hooks)"]
        S4["4. Install codex shim\n(PATH wrapper)"]
        S5["5. Init trace store\n~/.aids/"]
        S6["6. Register session daemon\n(optional, auto-start)"]
    end

    subgraph ClaudeHook["Claude Code Integration"]
        CHS["~/.claude/settings.json\nhooks.preToolUse[]\nhooks.postToolUse[]"]
    end

    subgraph CodexShim["Codex Integration"]
        CSH["~/.local/bin/codex-shim\nwraps native codex binary\ninjects AIDS_SESSION_ID"]
    end

    CURL --> S1 --> S2 --> S3 --> S4 --> S5 --> S6
    S3 --> ClaudeHook
    S4 --> CodexShim

    style Install fill:#0f3460,color:#eee
    style ClaudeHook fill:#1a1a2e,color:#eee
    style CodexShim fill:#16213e,color:#eee
```

---

## Rating & Adaptive Feedback Loop

```mermaid
graph LR
    subgraph Ops["Operations"]
        OP1["Write op by agent-A\n(trace_001)"]
        OP2["Edit op by agent-B\n(trace_002)"]
    end

    subgraph Ratings["Ratings"]
        RT1["agent-C rates trace_001: 👍\n'good baseline'"]
        RT2["agent-D rates trace_002: 👎\n'broke format contract'"]
    end

    subgraph Feedback["Adaptive Signal"]
        AGG["Aggregate rating\nper session/role"]
        WARN["Conflict warning\nto future agents"]
    end

    OP1 --> RT1 --> AGG
    OP2 --> RT2 --> AGG
    AGG --> WARN
    WARN -->|"injected by PreToolUse\nwhen score < threshold"| Ops
```

---

## Directory Structure

```
~/.aids/                           # Global store (cross-project)
├── sessions/
│   └── {session_id}.json         # SessionRecord
├── traces/
│   └── YYYY-MM-DD.jsonl          # TraceRecord (append-only)
├── index/
│   └── {base64_path}.json        # [trace_id...] per resource
├── ratings/
│   └── YYYY-MM-DD.jsonl          # RatingRecord (append-only)
└── config.json                   # Global config

aids-tools/                       # This project (implementation; current checkout may be selftools)
├── docs/
│   ├── architecture.md           # This file
│   ├── data-model.md             # Schema definitions
│   └── hook-contract.md          # Hook interface spec
├── schemas/                      # JSON Schema files (v1 contract)
│   ├── tool-envelope.schema.json
│   ├── pre-tool-use-output.schema.json
│   ├── post-tool-use-output.schema.json
│   ├── session-record.schema.json
│   ├── trace-record.schema.json
│   ├── rating-record.schema.json
│   └── resource-index.schema.json
├── hooks/
│   ├── pre_tool_use.sh           # PreToolUse hook
│   └── post_tool_use.sh          # PostToolUse hook
├── bin/
│   ├── aids-session               # Session register/lookup CLI
│   ├── aids-trace                 # Trace query CLI
│   └── aids-rate                  # Rating CLI
├── lib/
│   ├── session.js                # SessionRecord CRUD
│   ├── trace.js                  # TraceRecord writer/reader
│   ├── index.js                  # Resource index
│   └── rating.js                 # Rating CRUD
├── install.sh                    # One-liner installer
└── README.md
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Trace storage | Append-only JSONL | Zero deps, grep-able, survives crashes |
| Resource index | Per-file JSON array | O(1) lookup, fits in RAM |
| Hook delivery (Claude) | settings.json preToolUse/postToolUse | Official API, survives upgrades |
| Hook delivery (Codex) | PATH shim wrapper | No native hook API yet |
| Session identity | ENV var `AIDS_SESSION_ID` | Available to hooks without file I/O |
| Intent capture | From `AIDS_INTENT` ENV or task comment | Declared, not inferred |
| Rating storage | Separate JSONL from traces | Ratings arrive after the fact |
| Install surface | `~/.aids/` global | Cross-project awareness |
| Tool coverage | Write + Read + Edit + Bash | All four native tools intercepted |
| Plugin pattern | settings.json hooks (Claude) + PATH shim (Codex) | Like superpower / claude-for-codex |
| Schema versioning | `selftools.hook.v1` | Machine-checkable contract for all runtimes |

---

## Emergent Properties

When this system is running:

1. **No explicit coordination needed** — agents discover peers through the trace index
2. **Write-before-read injection** — agent learns "Jane wrote this 2m ago for X" before overwriting
3. **Conflict detection** — if two agents hold write locks on overlapping resources, PreToolUse warns
4. **Bad actor surface** — a K-labeled operation gets rated 👎 by everyone → suppressed in future sessions
5. **Role emergence** — over time, trace patterns reveal which sessions specialize in which resources

This is not orchestration. It is **consciousness**: each agent sees more of the shared world than before.

---

## Plugin Compatibility Pattern

AIDS follows the install pattern of [superpower](https://github.com/obra/superpowers) and [claude-for-codex](https://github.com/Shiyao-Huang/claude-for-codex):

### Claude Code Plugin (settings.json hooks)

```json
{
  "hooks": {
    "preToolUse": [
      {
        "matcher": "Write|Edit|Read|Bash",
        "hooks": [{ "type": "command", "command": "~/.aids/hooks/pre_tool_use.sh" }]
      }
    ],
    "postToolUse": [
      {
        "matcher": "Write|Edit|Read|Bash",
        "hooks": [{ "type": "command", "command": "~/.aids/hooks/post_tool_use.sh" }]
      }
    ]
  }
}
```

### Codex Plugin (PATH shim)

```bash
# ~/.local/bin/codex → wraps /usr/local/bin/codex
# Injects AIDS_SESSION_ID, AIDS_ROLE, AIDS_INTENT
# Delegates to ~/.aids/hooks/ for pre/post interception
```

### One-Liner Install

```bash
curl -sfL https://raw.githubusercontent.com/.../install.sh | bash
```

Detects runtime (claude/codex/both), writes hooks, patches settings.json, installs shim, inits `~/.aids/`.
