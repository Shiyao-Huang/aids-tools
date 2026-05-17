# AIM research: installer + hook surfaces for AIDS

> Date: 2026-05-18 (Asia/Shanghai). Scope: research notes for implementing an identity-aware tool wrapper where every agent operation leaves an attributed, queryable chain.

## 0. Synthesis for the wrapper design

`AIDS` should ship as a **thin runtime installer + hook adapters + local operation graph**:

1. **Installer pattern:** copy `claude-for-codex`'s one-line, idempotent installer shape: detect runtime homes, clone/update package, build, install skills, register MCP, and support `--uninstall`.
2. **Distribution pattern:** copy Superpowers' marketplace/plugin pattern for discoverability: plugin manifests should point to a Git repo, bundle skills/hooks, and support native plugin installation where possible.
3. **Claude Code integration:** use `~/.claude/settings.json`, `.claude/settings.json`, or plugin `hooks/hooks.json`. Claude Code hooks are the strongest surface: `PreToolUse` can block and add model-visible context; `PostToolUse` can log/replace model-visible output after successful tools.
4. **Codex integration:** use `~/.codex/hooks.json` or inline `[hooks]` in `config.toml`. Current official docs and source show hook support for Bash, `apply_patch`, and MCP tools, but not all tool classes. Tool handlers must emit `pre_tool_use_payload`/`post_tool_use_payload`, so unsupported tools require fallback transcript/MCP wrapping.
5. **Operation-chain storage:** use GitNexus as the model for local graph storage: per-repo `.gitnexus/` DB + global registry. For `AIDS`, adapt this to `.aids/` with `Session`, `Operation`, `Resource`, `Task`, and `Review` nodes and typed edges.

---

## 1. `claude-for-codex` `install.sh` structure

Source: <https://github.com/Shiyao-Huang/claude-for-codex> and raw installer <https://raw.githubusercontent.com/Shiyao-Huang/claude-for-codex/main/install.sh>.

### Key structure

**One-line entrypoint and strict shell mode:**

```bash
#!/usr/bin/env bash
# claude-for-codex — One-line installer
# Usage: curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/claude-for-codex/main/install.sh | bash
set -euo pipefail
REPO="https://github.com/Shiyao-Huang/claude-for-codex.git"
```

**Codex home discovery:**

```bash
detect_codex_home() {
  if [ -n "${CODEX_HOME:-}" ]; then echo "$CODEX_HOME"; return; fi
  local codex_bin
  codex_bin=$(command -v codex 2>/dev/null || true)
  if [ -n "$codex_bin" ]; then
    local codex_dir
    codex_dir="$(dirname "$(dirname "$codex_bin")")/.codex"
    if [ -d "$codex_dir" ]; then echo "$codex_dir"; return; fi
  fi
  if [ -d "${XDG_CONFIG_HOME:-$HOME/.config}/codex" ]; then
    echo "${XDG_CONFIG_HOME:-$HOME/.config}/codex"; return
  fi
  echo "$HOME/.codex"
}
```

**Install locations:**

```bash
CODEX_HOME=$(detect_codex_home)
INSTALL_DIR="${CODEX_CLAUDE_DIR:-$CODEX_HOME/claude-for-codex}"
SKILLS_DIR="$CODEX_HOME/skills"
CONFIG_FILE="$CODEX_HOME/config.toml"
```

**Update-or-clone + build:**

```bash
if [ -d "$INSTALL_DIR/.git" ]; then
  cd "$INSTALL_DIR"
  git stash --quiet 2>/dev/null || true
  git checkout -- . 2>/dev/null || true
  git fetch origin && git reset --hard origin/main || warn "Git update failed"
else
  git clone --depth 1 "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
npm install --production=false
npm run build
```

**Skills and MCP registration:**

```bash
mkdir -p "$SKILLS_DIR"
for skill_dir in skills/*/; do
  skill_name=$(basename "$skill_dir")
  mkdir -p "$SKILLS_DIR/$skill_name"
  cp "$skill_dir/SKILL.md" "$SKILLS_DIR/$skill_name/SKILL.md"
done

cat >> "$CONFIG_FILE" <<TOML
# claude-for-codex MCP server
[mcp_servers.claude-code]
command = "node"
args = ["$INSTALL_DIR/dist/index.js"]
TOML
```

### Mapping to `AIDS`

Use this as the base installer skeleton:

```bash
curl -sfL https://raw.githubusercontent.com/<org>/aids-tools/main/install.sh | bash
```

Installer responsibilities:

- detect `CLAUDE_HOME`/`~/.claude` and `CODEX_HOME`/`~/.codex`;
- clone/update core into `${AIDS_HOME:-$HOME/.aids}/core`;
- install runtime skills/rules explaining the self-aware tool protocol;
- register MCP server `[mcp_servers.aids]` for both runtimes where supported;
- install Claude `settings.json` hooks and Codex `hooks.json` hooks;
- create a session registry at `~/.aids/sessions/`;
- support `--uninstall` to remove hooks, skills, MCP entries, and generated files.

---

## 2. Superpowers install pattern

Sources: <https://github.com/obra/superpowers> and marketplace <https://github.com/obra/superpowers-marketplace>.

Superpowers does **not** rely on a single universal shell installer. It uses native plugin/marketplace flows per harness.

### Claude Code install pattern

```bash
/plugin install superpowers@claude-plugins-official
```

Community marketplace fallback:

```bash
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

### Codex install pattern

```text
/plugins
# search: superpowers
# select: Install Plugin
```

### Marketplace manifest excerpt

From `.claude-plugin/marketplace.json` in `obra/superpowers-marketplace`:

```json
{
  "name": "superpowers-marketplace",
  "plugins": [
    {
      "name": "superpowers",
      "source": {
        "source": "url",
        "url": "https://github.com/obra/superpowers.git"
      },
      "description": "Core skills library: TDD, debugging, collaboration patterns, and proven techniques",
      "version": "5.1.0",
      "strict": true
    }
  ]
}
```

### Mapping to `AIDS`

Use **both** distribution channels:

- **curl installer** for fast bootstrap and machines without marketplace setup;
- **plugin marketplace** for official Claude/Codex-native installation once stable.

Recommended plugin contents:

```text
.aids-plugin/
  plugin.json              # name/version/source
  hooks/hooks.json          # runtime hook declarations
  skills/using-aids/SKILL.md
  skills/operation-chain/SKILL.md
  bin/aids-pre-tool
  bin/aids-post-tool
```

The Superpowers lesson: skills are not optional docs; they are runtime behavior triggers. `AIDS` should install a `using-aids` skill that makes agents ask: “who touched this resource and why?” before writes.

---

## 3. Claude Code `settings.json` hooks reference

Sources: Claude Code Hooks reference <https://docs.anthropic.com/en/docs/claude-code/hooks> and guide <https://docs.anthropic.com/en/docs/claude-code/hooks-guide>.

### Hook locations

Claude Code hook config can live in:

```text
~/.claude/settings.json          # user scope
.claude/settings.json            # project scope, shareable
.claude/settings.local.json      # project local, not committed
hooks/hooks.json                 # plugin-bundled hook config
```

### Config shape

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/aids-pre-tool.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/aids-post-tool.sh"
          }
        ]
      }
    ]
  }
}
```

Matchers for tool events run against `tool_name`; examples include `Bash`, `Edit|Write`, and `mcp__.*`.

### PreToolUse input/decision excerpt

Claude sends JSON on stdin, e.g.:

```json
{ "tool_name": "Bash", "tool_input": { "command": "rm -rf /tmp/build" } }
```

A blocking response:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Destructive command blocked by hook"
  }
}
```

### PostToolUse input/decision excerpt

`PostToolUse` receives both the original input and result:

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": { "file_path": "/path/to/file.txt", "content": "file content" },
  "tool_response": { "filePath": "/path/to/file.txt", "success": true },
  "duration_ms": 12
}
```

It can add context or replace model-visible output:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "Trace recorded as op_01HY...",
    "updatedToolOutput": {
      "stdout": "[redacted]",
      "stderr": "",
      "interrupted": false,
      "isImage": false
    }
  }
}
```

### Mapping to `AIDS`

Claude adapter design:

- `PreToolUse` on `Read|Edit|Write|MultiEdit|Bash|mcp__.*`:
  - resolve `session_id` to identity and task;
  - extract resource path/command target;
  - query `~/.aids/index/` for recent operations;
  - return `additionalContext`: last writer, purpose, timestamp, rating, and conflict warning;
  - optionally deny dangerous writes when a lock or bad-rated operation exists.
- `PostToolUse`:
  - write `TraceRecord` to `~/.aids/traces/YYYY-MM-DD.jsonl`;
  - update per-resource index;
  - emit trace id back as `additionalContext`.

---

## 4. Codex CLI hook/tool interception points

Sources: official Codex Hooks docs <https://developers.openai.com/codex/hooks> and OpenAI Codex source `codex-rs/core/src/tools/registry.rs` / `hook_runtime.rs` at <https://github.com/openai/codex>.

### Hook locations

Codex discovers hooks in:

```text
~/.codex/hooks.json
~/.codex/config.toml
<repo>/.codex/hooks.json
<repo>/.codex/config.toml
```

Plugins can also bundle `hooks/hooks.json` when plugin hooks are enabled.

### Codex hook config excerpt

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use_policy.py\"",
            "statusMessage": "Checking Bash command"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/post_tool_use_review.py\""
          }
        ]
      }
    ]
  }
}
```

Equivalent TOML:

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use_policy.py"'
timeout = 30
```

### PreToolUse fields and deny/context response

Codex `PreToolUse` includes:

```text
turn_id, tool_name, tool_use_id, tool_input
```

Canonical tool names include `Bash`, `apply_patch`, and MCP names such as `mcp__fs__read`. For `Bash` and `apply_patch`, the docs say `tool_input.command` is used.

Deny shape:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Destructive command blocked by hook."
  }
}
```

Add model-visible context:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "The pending command touches generated files."
  }
}
```

Current caveat from docs: `permissionDecision: "ask"`, legacy approve, `updatedInput`, `continue: false`, `stopReason`, and `suppressOutput` are parsed but not supported yet.

### PostToolUse support and limitations

Codex docs state that `PostToolUse` runs after supported tools, including Bash, `apply_patch`, and MCP calls. They also state it **does not intercept everything yet**, including incomplete richer shell interception and no `WebSearch`/other non-shell, non-MCP tool calls.

### Source-level interception point

`CoreToolRuntime` defaults to no hook payload, meaning each tool handler must opt in:

```rust
fn post_tool_use_payload(
    &self,
    _invocation: &ToolInvocation,
    _result: &dyn ToolOutput,
) -> Option<PostToolUsePayload> {
    None
}

fn pre_tool_use_payload(&self, _invocation: &ToolInvocation) -> Option<PreToolUsePayload> {
    None
}
```

The registry runs pre-hooks before the tool handler:

```rust
if let Some(pre_tool_use_payload) = tool.pre_tool_use_payload(&invocation) {
    match run_pre_tool_use_hooks(...).await {
        PreToolUseHookResult::Blocked(message) => {
            let err = FunctionCallError::RespondToModel(message);
            return Err(err);
        }
        PreToolUseHookResult::Continue { updated_input: Some(updated_input) } => {
            invocation = tool.with_updated_hook_input(invocation, updated_input)?;
        }
        PreToolUseHookResult::Continue { updated_input: None } => {}
    }
}
```

After successful execution, it runs post-hooks if the tool produced a post payload:

```rust
let post_tool_use_payload = if success {
    guard.as_ref().and_then(|result| result.post_tool_use_payload.clone())
} else {
    None
};

if let Some(post_tool_use_payload) = post_tool_use_payload {
    run_post_tool_use_hooks(...).await
}
```

### Mapping to `AIDS`

Codex adapter design:

- Install `.codex/hooks.json` for supported tools.
- Match `Bash|apply_patch|Edit|Write|mcp__.*` where aliases are available.
- Treat Codex hook coverage as **best-effort**, not total coverage.
- For unsupported built-ins, add fallback layers:
  - MCP wrapper for file/resource operations;
  - shell command wrappers for `git`, `sed`, `python`, etc.;
  - transcript tailing for non-intercepted operations;
  - optional patch to Codex tool handlers if running a fork.

---

## 5. GitNexus project for operation-chain storage

Source: <https://github.com/abhigyanpatwari/GitNexus>.

GitNexus is useful because it already models the thing `AIDS` needs: a local, queryable graph for agent context.

### Relevant GitNexus architecture

From GitNexus README/ARCHITECTURE:

```text
Indexes any codebase into a knowledge graph — every dependency, call chain,
cluster, and execution flow — then exposes it through smart tools so AI agents never miss code.
```

Storage layout:

```text
<repo>/.gitnexus/
  ├── lbug           # LadybugDB database
  ├── lbug.wal       # Write-ahead log
  ├── lbug.lock      # Single-writer lock
  └── meta.json      # lastCommit, indexedAt, stats

~/.gitnexus/
  └── registry.json  # Global repo registry (MCP discovery)
```

GitNexus states that `gitnexus analyze` stores an index inside `.gitnexus/` and registers a pointer in `~/.gitnexus/registry.json`; the MCP server reads that registry and lazily opens repo DB connections.

### Schema excerpt

GitNexus uses separate node tables and one typed relation table:

```ts
export const PROCESS_SCHEMA = `
CREATE NODE TABLE Process (
  id STRING,
  label STRING,
  heuristicLabel STRING,
  processType STRING,
  stepCount INT32,
  communities STRING[],
  entryPointId STRING,
  terminalId STRING,
  PRIMARY KEY (id)
)`;

export const RELATION_SCHEMA = `
CREATE REL TABLE ${REL_TABLE_NAME} (
  ...
  FROM Function TO Process,
  FROM Method TO Process,
  FROM Route TO Process,
  FROM Tool TO Process,
  type STRING,
  confidence DOUBLE,
  reason STRING,
  step INT32
)`;
```

### Mapping to `AIDS`

Adopt the same storage idea, but for operations instead of code symbols:

```text
~/.aids/
  sessions/                 # session_id -> role, goal, task, runtime
  registry.json              # repos/workspaces known to the tool layer
  traces/YYYY-MM-DD.jsonl    # append-only raw events
  ratings/YYYY-MM-DD.jsonl   # peer evaluation on operations

<repo>/.aids/
  opgraph/lbug               # optional graph DB for fast chain queries
  meta.json                  # lastTrace, indexedAt, repo identity
```

Suggested graph schema:

```sql
CREATE NODE TABLE Session (
  id STRING,
  runtime STRING,
  role STRING,
  taskId STRING,
  goal STRING,
  startedAt STRING,
  PRIMARY KEY(id)
);

CREATE NODE TABLE Resource (
  id STRING,
  path STRING,
  kind STRING,
  PRIMARY KEY(id)
);

CREATE NODE TABLE Operation (
  id STRING,
  tool STRING,
  action STRING,
  startedAt STRING,
  endedAt STRING,
  status STRING,
  summary STRING,
  PRIMARY KEY(id)
);

CREATE NODE TABLE Review (
  id STRING,
  rating STRING,
  comment STRING,
  reviewerSessionId STRING,
  createdAt STRING,
  PRIMARY KEY(id)
);

CREATE REL TABLE OpRelation (
  FROM Session TO Operation,
  FROM Operation TO Resource,
  FROM Operation TO Operation,
  FROM Review TO Operation,
  type STRING,       -- PERFORMED, READS, WRITES, FOLLOWS, RATES
  confidence DOUBLE,
  reason STRING,
  step INT32
);
```

Query interface mirroring GitNexus resources:

```text
aids://sessions
aids://resource/{path}/op-chain
aids://operation/{id}
aids://resource/{path}/ratings
```

This directly implements the cabinet metaphor: when an agent opens a file, `PreToolUse` queries `aids://resource/<path>/op-chain` and sees the labels left by other agents.

---

## 6. Minimal implementation blueprint

### Installer

```bash
curl -sfL https://raw.githubusercontent.com/<org>/aids-tools/main/install.sh | bash
```

Installer phases:

1. detect Claude/Codex homes;
2. clone/update `~/.aids/core`;
3. create `~/.aids/{sessions,traces,ratings,index}`;
4. install `using-aids` skills into Claude/Codex skill/plugin dirs;
5. register MCP server `aids`;
6. write Claude hooks into `~/.claude/settings.json` or plugin `hooks/hooks.json`;
7. write Codex hooks into `~/.codex/hooks.json` or `.codex/config.toml`;
8. support `--uninstall`.

### Pre hook pseudocode

```python
payload = json.load(sys.stdin)
session = registry.resolve(payload["session_id"])
resource = extract_resource(payload["tool_name"], payload["tool_input"])
recent = index.last_ops(resource, limit=5)

print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": render_awareness(session, resource, recent)
  }
}))
```

### Post hook pseudocode

```python
payload = json.load(sys.stdin)
trace = TraceRecord.from_hook_payload(payload)
trace_store.append(trace)
index.update(trace.resource, trace.id)
print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": f"AIDS trace recorded: {trace.id}"
  }
}))
```

## 7. Design decision

Start with append-only JSONL + per-resource index for reliability. Add the GitNexus-style LadybugDB graph after the raw trace contract is stable. Raw traces are the audit log; the graph is an acceleration/query layer.
