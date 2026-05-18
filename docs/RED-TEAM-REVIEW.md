# AIDS Design Red-Team Review

> **Reviewer**: Red-Team Design Reviewer (session `c2c97484`, role=reviewer)
> **Date**: 2026-05-18
> **Scope**: `bin/selftools` (2634 lines), `install.sh`, hooks, tests, docs

Review stance: every design choice gets the sharpest 3 questions. Each section names specific code locations, worst-case risk, and principle violations. This is a failure-oriented audit — it does not propose redesigns, only exposes cracks.

---

## 1. `aids q` — Query Router Decoupling

**Code**: `bin/selftools:1930-1936` (`QUERY_RESOLVERS` dict), `bin/selftools:1959-1989` (`cmd_query`)

### Sharpest Questions

**Q1: Is the resolver registry actually decoupled, or is it a hardcoded dict that silently skips unknown modules?**

The "registry" is a plain Python dict (`QUERY_RESOLVERS = {"identity": resolve_identity, ...}`). Adding a new resolver requires editing `bin/selftools` itself — there is no plugin/discovery mechanism. The `_query_enabled_modules()` function (line 1626) filters config modules against `QUERY_RESOLVERS.keys()`, so a config entry pointing to a non-existent module is silently dropped with no warning. A user who adds `"modules": ["custom_analyzer"]` to `config.json` gets zero feedback that it was ignored.

**Q2: Does `load_aids_config()` merge user config over defaults safely, or can a malformed config silently downgrade security?**

`_deep_merge_dict` (line 1580) does recursive merge — user values override defaults. This means `"signature": {"enabled": false}` in config silently disables signature checking. There is no validation schema, no "protected keys" list, and no doctor check for security-relevant settings. Any agent with write access to `~/.aids/config.json` can neuter the entire audit system.

**Q3: Does the query router fan-out actually reduce latency, or does it hide expensive work behind a compact summary?**

`cmd_query` (line 1959) runs every enabled resolver sequentially. There is no per-resolver timeout, no parallelism, no caching. If `resolve_impact` triggers GitNexus and it hangs for 8 seconds (line 878: `timeout=8`), the whole query blocks. Compact output (line 1954-1956) simply truncates at `max_chars` with `text[:max_chars-2] + "..."` — there is no guarantee that critical facts (bad ratings, failed signatures) survive truncation.

### Worst-Case Risk

An agent edits `config.json` to disable `signature` and `impact`, then runs `aids q <file>`. Output shows green "ok" status for all modules. Agent proceeds to edit a high-risk file that was actually just corrupted by another agent. **Severity: HIGH** — audit bypass via mutable config.

### Principle Violation

Violates "every fallback must lower confidence, not silently report success" (cross-cutting rule #6). Disabled modules report `status: "disabled"` in JSON but compact text just omits them with no warning.

---

## 2. 打卡签字系统 (Signature / Hash Chain)

**Code**: `bin/selftools:1805-1839` (`resolve_signature`), `bin/selftools:461-469` (`sha256_file`)

### Sharpest Questions

**Q1: What prevents a malicious agent from editing `~/.aids/traces/YYYY-MM-DD.jsonl` and recomputing downstream hashes?**

Nothing. The "hash chain" in AIDS is `pre_hash` and `post_hash` on each trace record — but these are file content hashes, not chain-linking hashes. There is no `prev_signature_hash` field. There is no merkle tree, no checkpoint anchoring, no signed root. `sha256_file` reads the target resource file, not the trace file itself. A trace record's "signature" is just evidence that the file existed at a certain state, not evidence that the trace record is authentic.

**Q2: If `~/.aids/traces` is directly edited (append-only violated), how is this detected?**

It is not detected. There is no `verify` command in the parser (`build_parser` has no `verify` subcommand). The existing review (previous version) mentioned `aids verify` but it does not exist in the code. `resolve_signature` checks if `pre_hash`/`post_hash` exist on a trace, but cannot verify they are correct because the original file content is gone after the next write. INV-4 in `docs/aids-invariants.md` claims "trace 文件 append-only，记录只增不减" but this is a property assumption, not an enforced invariant.

**Q3: Can two concurrent writers create a hash chain gap?**

Yes. `append_jsonl` (line 454) uses `FileLock` to serialize writes, but `sha256_file` is called *before* the lock in `save_pending` (line 834) and *after* the tool execution in `cmd_hook_post_tool_use` (line 1048). Between these two points, another agent can modify the same file, making `pre_hash` stale. The hash chain records an inconsistent state transition without flagging it.

### Worst-Case Risk

A compromised agent deletes or modifies trace JSONL files. There is no detection mechanism. The "打卡签字" system provides file-level integrity evidence but provides zero trace-level tamper evidence. **Severity: CRITICAL** — the audit trail itself is unauditable.

### Principle Violation

Violates "every security claim must state threat model and forge-cost level" (cross-cutting rule #3). The invariant document claims "不可篡改" (INV-4) but this is only true under the assumption that no external process modifies the files — an assumption that cannot be enforced.

---

## 3. Token 压缩 / 自适应截断

**Code**: `bin/selftools:472-477` (`short()`), `bin/selftools:1691-1702` (`_compact_trace`), `bin/selftools:1943-1956` (`format_query_text`)

### Sharpest Questions

**Q1: Is the adaptive truncation ratio computed or hardcoded?**

Hardcoded. `short(s, n=160)` at line 472 simply truncates at character count `n`. `_compact_trace` at line 1691 picks a fixed set of fields with `intent_max=80` (hardcoded default). `format_query_text` truncates at `max_chars` (default 1200 from config, line 1987). There is no "adaptive" logic — no risk-weighted prioritization, no dynamic budget allocation based on content importance.

**Q2: What information is lost when compact mode truncates, and how does an agent recover it?**

The truncation at line 1954-1956 (`text[:max_chars-2] + "..."`) is position-based, not priority-based. It can cut off the `ratings` module entirely if `identity` + `history` + `signature` + `impact` already used the budget. The `--full` flag exists but an agent in a hook context (PreToolUse) cannot choose `--full` — it gets whatever the compact formatter produces. The footer does not show hidden counts or a recovery command.

**Q3: Does `_compact_trace` lose operation-critical fields?**

Yes. `_compact_trace` (line 1691) drops `pre_hash`, `post_hash`, `duration_ms`, `tool_use_id`, `team_id`, `cwd`, and `metadata`. If the only record of a destructive operation (delete) is in the compact output, the agent cannot see the file's pre-deletion hash or the tool_use_id needed to trace the operation chain.

### Worst-Case Risk

Compact mode hides a `bad` rating on a trace because the `ratings` resolver output is truncated. Agent proceeds with edit. **Severity: HIGH** — truncation is not risk-aware.

### Principle Violation

Violates "every compact output must reveal hidden counts and recovery command" (cross-cutting rule #2). `format_query_text` produces no disclosure footer.

---

## 4. 信息还原度 (Storage Integrity)

**Code**: `bin/selftools:454-458` (`append_jsonl`), `bin/selftools:205-209` (`write_json_atomic`)

### Sharpest Questions

**Q1: Does the storage layer ever truncate data?**

At the append layer, no — `append_jsonl` writes the full `json_line(record)`. But at the *capture* layer, yes — `cmd_hook_post_tool_use` at line 1073 stores `short(event.get("tool_response"), 500)` in `metadata.tool_response_preview`, capping tool output at 500 chars. The full tool response is lost permanently. Also, `detect_resources` for Bash at line 718 stores `short(tool_input.get("command"), 240)` — long shell commands are truncated before indexing.

**Q2: Can JSONL append-only lose data under high concurrency?**

Possible but unlikely in practice. `append_jsonl` acquires `FileLock` (fcntl or rename) before writing. The lock is per-file (sha256 of the target file path, line 429-437). Two concurrent hooks writing to the same daily trace file will serialize correctly. However, there is no write acknowledgment or fsync — if the process crashes between `fh.write()` and lock release, the last line may be lost. The `write_json_atomic` for index/session uses `os.replace()` which is atomic on POSIX, but the JSONL append path has no such guarantee.

**Q3: Can the index (`update_index`, line 601) lose data?**

Yes. `update_index` keeps `trace_ids = trace_ids[-500:]` (line 609) — only the last 500 trace IDs per resource are retained. Older trace IDs are silently evicted from the index. The traces themselves remain in JSONL files, but they become invisible to `who-touched` and `recent_traces` (which reads from the index, not from full JSONL scan). For a heavily-modified file, history beyond the last 500 operations is effectively lost for query purposes.

### Worst-Case Risk

A long-running project accumulates >500 traces on a critical config file. The index silently drops the earliest traces, including the original creation trace with its `pre_hash=None` → `post_hash=X` chain origin. Any later hash chain verification starts from an arbitrary mid-point. **Severity: MEDIUM** — data exists but becomes undiscoverable.

### Principle Violation

Violates "storage must preserve evidence; compact output may summarize but must disclose what was hidden" (review stance). The 500-trace index cap is undocumented and not disclosed in any output.

---

## 5. 并发锁 (Concurrency)

**Code**: `bin/selftools:221-427` (`FileLock` class), `bin/selftools:429-451` (`lock_path_for`, `clean_all_stale_locks`)

### Sharpest Questions

**Q1: Does fcntl POSIX flock work on NFS?**

No. `fcntl.flock` is local-filesystem only on most implementations. On NFS, flock may be emulated by the client or silently behave as a no-op. The code at line 309 (`_try_acquire_fcntl_nb`) does not detect or warn about NFS mounts. If `~/.aids` is on NFS (common in shared server environments), two agents on different machines can both acquire the same lock simultaneously, leading to interleaved JSONL writes.

**Q2: Is the stale detection timeout (300 seconds) appropriate?**

`STALE_SECONDS = 300` (line 229) assumes a lock holder that hasn't updated in 5 minutes is dead. But a legitimate long-running tool call (e.g., a 10-minute `aids impact` grep scan, line 1842-1864 which has no timeout and `rglob("*")` over the entire project) could hold a lock for longer. The `_break_stale_lock` at line 278 checks if the PID is alive via `os.kill(pid, 0)`, but the PID could be alive doing legitimate work — the lock file was created for a different resource but shares the same locks directory.

Actually, re-reading the code: each resource gets its own lock file via `lock_path_for`. So the stale timeout is per-resource, not global. But the `clean_all_stale_locks` function (line 440) runs on every `ensure_layout()` call and removes *all* locks older than 300 seconds based on mtime — even if the holder is still alive. This is a race condition: `_clean_stale_mtime` (line 297) can remove a lock that `_break_stale_lock` would have kept.

**Q3: What happens on Windows?**

The non-fcntl path (`_try_acquire_rename`, line 321) uses `os.rename()` which is atomic on Windows only if the target does not exist (it replaces on Unix). The code at line 333 catches `OSError` and treats it as "lock held". But the context manager path (line 391-402) polls at 50ms intervals with a 5-second default timeout — far too aggressive for slow operations. And `_clean_stale_mtime` can remove a lock file that another process just created via rename, between the rename and the file open.

### Worst-Case Risk

Two agents on NFS both acquire the same lock, interleave writes to the same JSONL file, producing corrupt JSON lines that crash all future `read_trace` calls. **Severity: MEDIUM** in single-machine deployments, **HIGH** on NFS/shared storage.

### Principle Violation

None explicitly stated, but the concurrency model is undeclared — the docs claim "FileLock guarantees mutual exclusion" (INV-1 proof) without stating the NFS/cross-machine exclusion.

---

## 6. GitNexus 集成

**Code**: `bin/selftools:867-906` (`gitnexus_enabled`, `run_gitnexus`, `gitnexus_file_context`)

### Sharpest Questions

**Q1: Does depending on an external binary violate the "zero dependency" principle?**

Yes, conditionally. The project claims "零依赖，Python stdlib only" but `run_gitnexus` at line 871 calls `shutil.which("gitnexus")` and `subprocess.run([gn, ...])`. This introduces:
- External binary dependency (gitnexus must be installed separately)
- Subprocess overhead on every PreToolUse hook for write tools (line 1016-1023)
- Non-deterministic behavior: same AIDS version produces different results depending on whether gitnexus is installed

**Q2: What is the timeout budget for GitNexus calls during a hook?**

8 seconds per call (line 878: `timeout=8`). For a PreToolUse hook on a file with multiple resources, each resource triggers a separate `gitnexus_file_context` call. Three resources = 24 seconds of blocking in the hook. The host runtime (Claude/Codex) may have its own hook timeout that kills the process before completion. If killed mid-write, the pending file exists but the post-hook never fires — the pending record is orphaned.

**Q3: Does the importance heuristic actually work?**

`gitnexus_file_context` at line 904 rates importance by counting keyword hits: `sum(tok in lowered for tok in ["critical", "route", "api", "handler", "caller", "impact", "process"])`. This is word-frequency analysis of natural language output. A file whose GitNexus output contains "this is a critical API handler for the main route" would score "high", while a file that is equally important but described as "core dispatch mechanism" would score "low". The heuristic is fragile and untested.

### Worst-Case Risk

GitNexus subprocess hangs for 8 seconds on every file write, adding 8+ seconds of latency to every Edit/Write tool call. Users uninstall AIDS because it makes their agent "slow". **Severity: MEDIUM** — performance, not correctness.

### Principle Violation

Violates the stated "零依赖" (zero dependency) principle. The GitNexus integration is properly optional (returns `None` if unavailable) but the code path still exists and the dependency is documented in CLAUDE.md as mandatory for impact analysis.

---

## 7. Install / Uninstall 覆盖

**Code**: `install.sh` (580 lines), `bin/selftools:2448-2479` (`cmd_doctor`)

### Sharpest Questions

**Q1: Are all new commands covered in install.sh?**

Checking `install.sh` symlink list (lines 241-252) against `build_parser` subcommands (lines 2493-2613):
- `aids q`/`query`/`ask` — covered (symlink to same binary)
- `aids export` — covered (same binary)
- `aids impact` — covered (same binary)
- `aids stats` — covered (same binary)
- `aids commit-stamp` — covered (same binary)
- `aids doctor` — covered (same binary)

All commands go through the same `bin/selftools` binary, so new subcommands automatically work after install. This is well-designed.

**Q2: Does `aids doctor` actually verify all installed components?**

`cmd_doctor` (line 2448) checks:
- data_dir exists (line 2451)
- sessions_dir exists (line 2452)
- traces_dir exists (line 2453)
- Claude settings contains "selftools" or "aids" (line 2457)
- Codex hooks contains "selftools" or "aids" (line 2458)
- Codex MCP config contains selftools/aids (line 2459)
- Lock mechanism type (line 2460)
- Locks directory exists (line 2464)

Missing checks:
- Does NOT verify the hook scripts are executable
- Does NOT verify the symlinks in `$BIN_DIR` point to valid targets
- Does NOT check config.json validity
- Does NOT check Python version compatibility
- Does NOT verify pending directory is clean
- Does NOT check for orphaned locks older than STALE_SECONDS
- Does NOT verify hook scripts match the installed version
- Success is determined by `all(c["ok"] for c in checks[:3])` — only the first 3 checks (data_dir, sessions, traces) determine pass/fail. Hook registration failures are non-fatal.

**Q3: What happens on reinstall with stale hook paths?**

`configure_claude_hooks` (install.sh line 266) calls `clean_hooks(data)` which removes existing selftools hook handlers before adding new ones. This is correct. But it does not verify that the hook script paths in the new configuration actually exist — if `$INSTALL_DIR` changed between installs, the new hook paths may point to a different location while the scripts are at the old location.

### Worst-Case Risk

After reinstall to a new directory, doctor passes (first 3 checks are directory existence) but hooks silently fail because hook script paths in settings.json point to the old install location. Every tool call loses its AIDS trace. **Severity: MEDIUM** — silent data loss.

### Principle Violation

Doctor's pass/fail criteria only checks the first 3 items. This violates "every fallback must lower confidence" — a partially-broken installation can report full health.

---

## 8. Bash 索引 (Resource Keying)

**Code**: `bin/selftools:585-594` (`index_key`, `index_path`), `bin/selftools:705-730` (`detect_resources`)

### Sharpest Questions

**Q1: Does sha256 hashing long commands as index keys reduce information density?**

For commands longer than 180 chars after base64 encoding, `index_key` at line 589 returns `f"sha256-{digest}"` — a 70-char hash that reveals nothing about the original command. When looking at index files in `~/.aids/index/`, a user or agent cannot tell which file a `sha256-*` index entry corresponds to without querying AIDS itself. For `bash:` resources, the index key is based on the truncated command (`short(cmd, 240)` at line 718), so commands over 240 chars are further truncated before indexing, AND commands over ~135 chars get sha256'd as the index filename. Double information loss.

**Q2: Can two different bash commands collide in the index?**

Theoretically yes: `base64.urlsafe_b64encode(cmd.encode())` is truncated at `rstrip("=")` and capped at 180 chars. Two commands with the same first ~135 UTF-8 bytes but different suffixes will produce the same base64 prefix and thus the same index key. The sha256 fallback prevents collision, but at the cost of making the index opaque.

**Q3: Are `bash:` resources actually useful for `who-touched` queries?**

Marginally. `detect_resources` at line 718 stores `f"bash:{short(cmd, 240)}"`. The `who-touched` command (`cmd_who_touched`, line 1116) calls `print_traces_for_resource` which calls `recent_traces` which looks up by `normalize_resource(arg)`. For a `bash:` query, the user would need to type the exact truncated command prefix. There is no fuzzy matching for bash commands.

### Worst-Case Risk

An agent runs a destructive bash command. The trace is indexed under an opaque sha256 key. `aids who-touched <file>` does not show bash commands that affected the file because `detect_resources` indexes bash commands separately from file paths. The bash→file mapping in `parse_bash_write_resources` (line 733) is correct but the index key is `bash:<cmd>`, not the target file path. So `who-touched file.py` misses bash operations that wrote to `file.py` via redirection. **Severity: MEDIUM** — bash write detection is parsed but indexed under the wrong key.

### Principle Violation

`parse_bash_write_resources` correctly extracts file targets from bash commands, and `detect_resources` adds both the `bash:` key AND the file paths. Re-reading line 718-719: resources gets `bash:cmd` AND then `parse_bash_write_resources` results (actual file paths). So bash writes ARE indexed under file paths too. This is actually correct — the severity of the bash-index issue is lower than initially assessed. Updating: **Severity: LOW**.

---

## 9. 身份一致性 (Identity Consistency)

**Code**: `bin/selftools:1031-1084` (`cmd_hook_post_tool_use`), QA finding in task DhUgtSgRyQ0U

### Sharpest Questions

**Q1: Why does the same session have `role=MISSING` in some traces but correct values in others?**

Root cause confirmed by QA (task DhUgtSgRyQ0U comment): `cmd_hook_post_tool_use` at line 1065-1067 reads `role` and `display_name` from the session dict. The session is loaded via `register_session(event, source="post-tool-use")` at line 1033. In the current code, `register_session` reads role from `os.environ.get("AIDS_ROLE")` (line 543). If the environment variable is not set (e.g., the hook was invoked in a subprocess that didn't inherit the env vars), the role falls back to the existing session file value, and if that's also missing, to `"unknown"`. The fix (line 1065-1067 now reads from `session.get("role")`) is correct but only works if `register_session` successfully loaded the session file — which it does via `read_json(path, {})` at line 523. If the session file doesn't exist yet (race between SessionStart and first PostToolUse), role is `"unknown"`.

**Q2: Can two different agents share the same session_id?**

Yes, if they use the same env vars. `session_id_from` at line 510 checks `AIDS_SESSION_ID` env var first. If two agent processes on the same machine share environment (e.g., both inherit from the same shell), they get the same session_id. The session file is overwritten by whoever writes last — `write_json_atomic` uses `os.replace()` which is last-writer-wins.

**Q3: Is `display_name` stable across session lifetime?**

No. `register_session` at line 542 reads `display_name` from env vars on every call. If the env var changes between calls (e.g., AHA updates `AHA_SESSION_NAME` mid-session), the display_name changes. Old traces retain the old display_name (stored in the trace record at line 1067), but the session file is overwritten with the new name. `whois` and `list-sessions` show the latest name, not the name that was active during each trace.

### Worst-Case Risk

Two agents share the same `AIDS_SESSION_ID` env var (common in AHA teams where the org-manager sets env vars before spawning). Both write to the same session file. `whois` shows one agent's identity for another agent's traces. **Severity: HIGH** — identity confusion in multi-agent environments.

### Principle Violation

Violates "identity display must prefer immutable per-trace actor_snapshot; mutable registry is fallback only" (cross-cutting rule #4). `who-touched` at line 1108 shows `sess.get("display_name")` from the current session file, not the trace's embedded `display_name`.

---

## 10. Playground 原则 (No Hardcoded "Must Enable")

**Code**: `bin/selftools:1562-1572` (`DEFAULT_QUERY_CONFIG`), `bin/selftools:867-868` (`gitnexus_enabled`)

### Sharpest Questions

**Q1: Are there hardcoded features that cannot be disabled?**

Yes. The trace recording itself cannot be disabled. `cmd_hook_post_tool_use` always writes to JSONL — there is no config toggle for "don't record this session's traces". A sandbox/playground agent that wants to experiment without polluting the audit trail has no option. The `trace_ids` are always appended, the index is always updated, and the timeline is always written.

**Q2: Can the `gitnexus` integration be truly disabled?**

`gitnexus_enabled` at line 867 returns `env_first("AIDS_GITNEXUS", ...) != "0"`. This means gitnexus is enabled *by default* — it runs on every PreToolUse for write tools (line 1016-1023) unless explicitly disabled via env var. There is no `config.json` toggle for this. The install.sh `--without-gitnexus` flag (line 87) sets `WITH_GITNEXUS=0` for the install script, but this does NOT set the env var for runtime hooks.

**Q3: Is there a "dry run" mode for hooks?**

No. There is no way to run AIDS hooks in observation-only mode. Every PostToolUse creates permanent trace records. The install.sh has `--dry-run` for the installer, but the hooks themselves have no such option. A testing or evaluation environment cannot use AIDS without writing real trace data.

### Worst-Case Risk

An evaluation run of 1000 test operations creates 1000+ trace records in the production `~/.aids` directory. These traces pollute the audit trail and cannot be distinguished from real operations. **Severity: LOW** — no correctness issue, but operational hygiene problem.

### Principle Violation

Violates the Playground principle: there should be a way to run AIDS in a non-recording mode for testing. Currently, the only option is to use a separate `AIDS_DATA_DIR` for tests.

---

## Overall Assessment

### Grade: **B-**

The system is architecturally sound for its stated purpose (identity-aware tracing for AI agents). The core loop — SessionStart → PreToolUse (save pending + show context) → PostToolUse (record trace + update index) — is well-designed and the code is clean. However, there are meaningful gaps:

### Critical Issues (must fix before production trust)

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| 1 | Config allows silent security bypass (disable signature/impact) | `bin/selftools:1590-1596` | HIGH |
| 2 | No trace-level tamper detection (audit trail is unauditable) | `bin/selftools:1805-1839` | CRITICAL |
| 3 | Session identity collision in multi-agent environments | `bin/selftools:510-515, 527-562` | HIGH |

### Important Issues (fix in next iteration)

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| 4 | Compact truncation is position-based, not risk-aware | `bin/selftools:1954-1956` | HIGH |
| 5 | Doctor only checks first 3 items for pass/fail | `bin/selftools:2466` | MEDIUM |
| 6 | GitNexus called by default, no config toggle | `bin/selftools:867-868` | MEDIUM |
| 7 | Index cap at 500 traces per resource is undocumented | `bin/selftools:609` | MEDIUM |

### Improvement Priority

1. **P0**: Add config validation — security-critical keys (`signature.enabled`, `impact.enabled`) cannot be disabled without explicit `aids config set --confirm` and doctor must flag them.
2. **P0**: Add trace-level integrity — at minimum, a daily root hash checkpoint written to a separate file. Even a simple `sha256(all-lines-in-trace-file)` written to `~/.aids/checkpoints/YYYY-MM-DD.json` after each `append_jsonl` would detect post-hoc tampering.
3. **P0**: Fix session identity collision — `register_session` should refuse to overwrite a session file belonging to a different PID/runtime/host combination without explicit confirmation.
4. **P1**: Make compact output risk-aware — bad ratings, failed signatures, and high-impact files must be non-droppable.
5. **P1**: Add doctor check for all installed components, not just first 3.
6. **P1**: Add config toggle for gitnexus in `~/.aids/config.json`.
7. **P2**: Document the 500-trace index cap and add a `--scan-full` flag to `who-touched` that reads JSONL directly.

---

*Review complete. This document should be updated after each P0 fix is implemented.*
