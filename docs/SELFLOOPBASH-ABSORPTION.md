# selfloopbash Absorption Spec

## Scope and source path note

The assignment asked to read `/Users/copizzah/Desktop/selfloopbash/`, but that path does not exist on this machine. The matching project found and used for this analysis is:

- `/Users/copizzah/Desktop/work/selfloopbash/`

This document is analysis-only. No production code was changed.

## Executive summary

Three selfloopbash features are worth absorbing into AIDS:

1. **True stale-write protection** — selfloopbash blocks writes when an existing file was not read by the current session, or when the file hash changed after the session's last read. AIDS currently records pre/post hashes but does not enforce this gate.
2. **SQLite ledger** — selfloopbash stores sessions, resources, events, conditions, hazards, evaluations, outcomes, thoughts, adaptation hints, and tool registry rows in a WAL SQLite database. AIDS currently uses JSON/JSONL files plus per-resource index files; it has no relational event chain or condition/hazard tables.
3. **Focused behavior tests** — selfloopbash has compact tests that directly prove stale-write blocking, ledger event-chain joins, hook behavior, Bash write tracing, and CLI strict/relaxed write checks. AIDS has broader tests, but its current “stale write” tests mostly prove pending/pre-hash capture, not actual stale-write blocking.

Recommended absorption strategy: **phase in behavior first, then storage**. Implement the stale-write gate against the current JSONL/index store first so the user-visible safety improvement lands quickly. Add SQLite as an optional sidecar mirror next, then migrate query/op-chain commands to prefer SQLite when present.

---

## Feature 1 — stale-write protection

### selfloopbash implementation details

Relevant files/functions:

- `aid/core.py`
  - `file_hash(path)` lines 72-83: SHA-256 hash of current file contents.
  - `Ledger.last_read(session_id, resource_id)` lines 788-797: fetches the latest `event_type='read'` for this session/resource.
  - `Ledger.awareness(session_id, path, cwd)` lines 1005-1043: gathers current hash, last read, peer writes, peer reads, evaluations, and GitNexus context.
  - `Ledger.pre_write_decision(session_id, path, cwd, strict_missing_read=False)` lines 1045-1132: core gate.
  - `compact_awareness_lines()` lines 1135-1175: turns awareness into bounded hook context.
  - `extract_patch_paths()`, `extract_bash_write_paths()`, `extract_read_paths()`, `extract_write_paths()` lines 1186-1246: discovers file resources touched by tools.
  - `handle_hook()` lines 1334-1475: wires PreToolUse/PostToolUse to the ledger.
- `aid/cli.py`
  - `cmd_check_write()` lines 202-213: exposes the gate as CLI; returns `2` on block.
  - `cmd_run()` lines 325-384: applies write checks before Bash commands and records Bash write events afterward.
- `hooks/aid-hook` lines 25-27: defaults `AID_LEDGER=$DATA/ledger.sqlite`, `AID_STRICT_MISSING_READ=1`, `AID_GITNEXUS=1`.

Core logic in `Ledger.pre_write_decision()`:

1. Normalize/ensure resource and compute current file hash through `awareness()`.
2. If the target does not exist, record an optional `resource-exists` condition and allow new-file writes.
3. If no prior read exists for this session/resource:
   - record a `missing-read` hazard;
   - record an unsatisfied `read-before-write` condition;
   - return `block` when strict, otherwise `warn`.
4. If a prior read exists, record a satisfied `read-before-write` condition.
5. If `last_read.after_hash != current_hash`, record a `stale-read` hazard plus failed `fresh-read` condition and return `block`.
6. If hashes match, record a satisfied `fresh-read` condition.
7. If peer writes/evaluations exist, return `warn`; otherwise return `allow`.

Hook behavior:

- PreToolUse records a generic `tool-pre` event, extracts write paths, calls `pre_write_decision()` for each path, merges decisions, records a `precondition-check` thought, and returns a hook block payload when needed.
- PostToolUse records generic tool events, read events, and write/patch events with current content hashes.

### AIDS current state in `bin/selftools`

Relevant functions:

- `sha256_file()` lines 461-469 computes hashes.
- `detect_resources()`, `parse_bash_write_resources()`, and `parse_apply_patch_resources()` lines 705-819 identify file resources.
- `save_pending()` lines 841-857 records `pre_hash` in a pending JSON file during PreToolUse.
- `cmd_hook_pre_tool_use()` lines 1016-1053 saves pending and prints recent context/impact context. It **does not block**.
- `cmd_hook_post_tool_use()` lines 1056-1109 uses the pending `pre_hash` plus current `post_hash` to classify `read/create/modify/delete/touch`, append JSONL traces/timeline, update the resource index, and remove pending.
- Existing desired behavior is already described in `docs/hook-contract.md` lines 713-727: fresh observation lock, new-file allowance, recent conflict warnings, and strict missing-read block.

Current gaps:

- No `last_read` lookup for same session/resource.
- No comparison of last read hash against current hash at PreToolUse.
- No strict missing-read block in PreToolUse.
- No hazard/condition record for policy decisions.
- `TestINV3_StaleWriteProtection` currently verifies pending/pre-hash behavior, not stale-read rejection.

### Absorption plan for AIDS

Add/modify these `bin/selftools` functions first:

1. Add `last_read_trace(resource: str, session_id: str) -> Optional[Dict[str, Any]]`.
   - Source: scan resource index trace IDs via `recent_traces(resource, limit=...)` and pick newest `operation == "read"` with same `session_id`.
2. Add `recent_write_conflicts(resource: str, session_id: str, window_ms: int) -> List[Dict[str, Any]]`.
   - Source: existing `recent_traces()`; filter `operation in {"create","modify","delete"}` and other sessions.
3. Add `pre_write_decision(resource: str, session: Dict[str, Any], mode: str = env_first("AIDS_WRITE_POLICY", ...) or "strict") -> Dict[str, Any]`.
   - Reuse `sha256_file()`, `last_read_trace()`, and `recent_write_conflicts()`.
   - Decisions: `allow`, `warn`, `block`, plus reason/context/policy metadata.
   - Match `docs/hook-contract.md` rules: new-file allow; missing read warn/block by mode; stale hash block; fresh hash allow/warn on conflicts.
4. Modify `cmd_hook_pre_tool_use()`.
   - For `WRITE_TOOL_NAMES`, call `pre_write_decision()` for each non-`bash:`/`mcp:` resource before allowing the write.
   - On block, emit top-level `decision: "block"`, `reason`, and `hookSpecificOutput.permissionDecision: "deny"`/`permissionDecisionReason`, then return non-zero only if the runtime expects non-zero blocking; otherwise follow current hook schema.
   - Continue to `save_pending()` for allowed/warn decisions.
5. Modify `cmd_hook_post_tool_use()`.
   - Store policy outcome in `trace["metadata"]["policy"]` as required by `docs/hook-contract.md` line 727.
6. Optional CLI: add `aids check-write <path>` mirroring selfloopbash `cmd_check_write()` for manual and test usage.

---

## Feature 2 — SQLite ledger

### selfloopbash implementation details

Relevant file/functions: `aid/core.py`.

Storage path:

- `default_ledger_path()` lines 60-61: `$AID_LEDGER` or `~/.aid/ledger.sqlite`.
- `Ledger.__init__()` lines 298-304: creates parent directory, opens `sqlite3.connect()`, sets `row_factory`, calls `init_schema()`.

Schema in `Ledger.init_schema()` lines 309-463:

- `PRAGMA journal_mode=WAL` for concurrent reads/writes.
- Tables:
  - `actors`
  - `sessions`
  - `goals`
  - `resources`
  - `events`
  - `claims`
  - `evaluations`
  - `outcomes`
  - `adaptation_hints`
  - `thoughts`
  - `conditions`
  - `hazards`
  - `tool_registry`
- Indexes on resource/event/session lookup paths, including `idx_events_resource_created`, `idx_events_session_resource`, `idx_goals_session_created`, `idx_evaluations_event`, `idx_outcomes_event`, `idx_thoughts_*`, and `idx_conditions_event`.

Core methods:

- `ensure_actor()`, `ensure_session()`, `set_goal()`, `current_goal()` keep identity/intent state.
- `ensure_resource()` lines 657-672 maps normalized file paths to stable `res-<hash>` IDs.
- `record_event()` lines 674-725 appends event rows and captures `after_hash` for read/write/patch events.
- `record_thought()` and `record_condition()` store rationale/preconditions.
- `add_evaluation()` records peer review and creates adaptation hints for good/bad/mixed verdicts.
- `add_hazard()` records missing-read/stale-read hazards.
- `event_chain()` lines 951-1003 joins event + thoughts + conditions + evaluations + outcomes + adaptation hints.
- `awareness()` lines 1005-1043 assembles current decision context from ledger tables.

### AIDS current state in `bin/selftools`

AIDS explicitly uses filesystem storage, not SQLite:

- Header lines 4-9: `~/.aids/sessions/*.json`, `traces/YYYY-MM-DD.jsonl`, `timeline/YYYY-MM-DD.jsonl`, `index/*.json`, `ratings/YYYY-MM-DD.jsonl`.
- `ensure_layout()` lines 78-81 creates directories.
- `FileLock` lines 221-427 provides file locks with stale-lock cleanup.
- `append_jsonl()` lines 454-459 appends line records under a lock.
- `write_json_atomic()` lines 205-209 writes JSON files atomically.
- `update_index()` lines 601-634 maintains bounded per-resource trace IDs and last writer metadata.
- `cmd_rate()` lines 1296-1317 writes ratings JSONL linked by trace ID.

Current gaps versus selfloopbash:

- No relational event chain table; `op-chain` currently prints recent traces for a resource.
- No conditions/hazards/thoughts/outcomes/adaptation hint tables.
- No tool registry equivalent.
- Ratings are separate JSONL records and are not joined into chain output except through query helper code.
- Querying all history requires scanning JSONL files and index files.

### Absorption plan for AIDS

Do not replace JSONL immediately. Add SQLite as an **optional sidecar mirror** first.

New functions/modules:

1. `ledger_path() -> Path`
   - `$AIDS_LEDGER` or `data_dir() / "ledger.sqlite"`.
2. `ledger_connect() -> sqlite3.Connection`
   - Set `row_factory`, `PRAGMA journal_mode=WAL`, possibly `PRAGMA busy_timeout=5000`.
3. `init_ledger_schema(conn)`
   - Start with minimal selfloopbash-compatible tables: `sessions`, `resources`, `events`, `conditions`, `hazards`, `evaluations`, `outcomes`, `thoughts`.
   - Add `tool_registry` later if dynamic hook coverage is needed.
4. `ledger_ensure_resource(conn, resource_path)` and `ledger_record_event(conn, trace, session)`.
   - Mirror every trace appended by `cmd_hook_post_tool_use()`.
5. `ledger_record_condition()` / `ledger_record_hazard()`.
   - Called by new `pre_write_decision()`.
6. `ledger_event_chain(trace_id_or_event_id)`.
   - Let `cmd_op_chain()` prefer SQLite chain if available; fall back to current JSONL/index behavior.
7. `migrate_jsonl_to_ledger()` or lazy backfill.
   - Optional command to backfill existing JSONL traces/ratings into SQLite.

Modified functions:

- `ensure_layout()` should initialize SQLite only when `AIDS_SQLITE_LEDGER=1` or once the feature becomes default.
- `cmd_hook_post_tool_use()` should mirror trace/timeline writes into SQLite after JSONL append succeeds.
- `cmd_rate()` should mirror ratings into `evaluations` or a dedicated ratings table; recommended mapping: ratings remain ratings JSONL but also create an `evaluations` row where `event_id/trace_id` matches the trace.
- `cmd_op_chain()`, `cmd_query()`, and `cmd_stats()` can gradually prefer SQLite for faster joins.

Risk control:

- JSONL remains canonical until SQLite mirror has parity tests.
- SQLite write failure should log and fail-open for tracing, not block tool execution.
- Use WAL + busy timeout to avoid replacing the current file lock safety model abruptly.

---

## Feature 3 — test coverage

### selfloopbash implementation details

Selfloopbash has 11 Python `unittest` tests in `tests/test_aid.py`. I ran them with:

```bash
python3 -m unittest tests.test_aid -v
```

Result: `Ran 11 tests in 5.104s — OK`.

Coverage highlights:

- `AidLedgerTests.test_stale_write_blocks_and_chain_keeps_evaluation` lines 23-43:
  - Session A reads a file.
  - Session B writes it and receives a bad evaluation.
  - Session A attempts write and gets `decision == "block"` with stale-write context.
  - Event chain retains evaluation and adaptation hints.
- `test_thoughts_and_conditions_are_queryable_on_chain` lines 45-63: verifies thought/condition chain joins.
- `test_gitnexus_context_can_mark_important_file` lines 65-94: verifies GitNexus-derived high importance.
- `test_awareness_is_budgeted_and_recent_first` lines 96-109: verifies bounded awareness context.
- `AidHookTests.test_hooks_record_goal_read_and_warn_on_missing_read_for_other_session` lines 125-162: verifies UserPromptSubmit, read recording, and missing-read warning.
- `test_codex_apply_patch_command_paths_are_traced` lines 164-188: verifies apply_patch path extraction and write gate.
- `test_non_file_tool_is_registered_and_traced` lines 191-216: verifies tool registry and non-file tool trace envelope.
- `AidCliTests.test_aid_run_records_bash_write_in_same_timeline` lines 246-264: verifies Bash write tracing.
- `test_cli_blocks_missing_read_by_default_and_can_relax` lines 274-283: verifies strict default block and `--allow-missing-read` warn behavior.
- `test_cli_registers_custom_tool` lines 285-313: verifies tool registry CLI.

### AIDS current state

AIDS already has broad coverage:

- `tests/test_selftools.py`: normalization, operation classification, index keys, GitNexus integration wrapper, sessions, trace/index, timeline, ratings, stats, export, query, who-touched, parser, resource detection.
- `tests/test_selftools_extra.py`: export, register-session, rate, heartbeat, whois, more Bash resource parsing, file lock stale cleanup, date range, retire session.
- `tests/test_invariants.py`: seven invariants plus full flow.
- `tests/trace-ratings.test.js`: Node trace/ratings module coverage.

Key gaps for this absorption:

- No test currently proves a write is blocked because the current session did not read an existing file.
- No test proves a stale read is blocked after another session modifies the same file.
- `TestINV3_StaleWriteProtection` lines 247-290 is named like stale protection but currently checks pending creation, post cleanup via trace existence, and `pre_hash` presence.
- No SQLite ledger tests exist.
- No event-chain test proves conditions/hazards/evaluations/adaptation hints are joined.

### Absorption test plan for AIDS

Add tests before implementation:

1. `tests/test_invariants.py`
   - `test_missing_read_blocks_existing_file_in_strict_mode`
   - `test_stale_read_blocks_after_peer_write`
   - `test_fresh_read_allows_write`
   - `test_blocked_pre_tool_use_does_not_create_write_trace`
2. `tests/test_selftools.py` or a new `tests/test_stale_write.py`
   - Unit-test `last_read_trace()`.
   - Unit-test `pre_write_decision()` for new file, missing read, stale hash, fresh hash, recent peer conflict.
3. `tests/test_selftools_extra.py`
   - CLI/hook-level test that PreToolUse emits `decision=block` and `permissionDecision=deny` when strict.
   - CLI `check-write` test if that command is added.
4. New `tests/test_sqlite_ledger.py`
   - Schema initializes with WAL.
   - Trace append mirrors into `events`.
   - Conditions/hazards are attached to the blocked decision event.
   - `op-chain` returns event + conditions + evaluations.
   - JSONL remains written when SQLite mirror is disabled.

---

## Not to absorb, and why

- **Do not rename AIDS back to AID/selfloopbash.** AIDS has current user-facing naming, legacy aliases, docs, installer, and tests.
- **Do not wholesale replace JSONL storage with SQLite in one step.** Current JSONL/index files are simple, inspectable, and already used by many commands. A sidecar mirror is lower risk.
- **Do not absorb selfloopbash's simpler Bash parser verbatim.** AIDS `parse_bash_write_resources()` already handles `2>`, `2>>`, `&>`, `&>>`, attached redirects, `tee` with multiple targets, `cp`/`mv`, and special device filtering more robustly.
- **Do not absorb selfloopbash's tool registry as a prerequisite for stale-write protection.** It is useful later, but stale-write safety can be implemented with existing `WRITE_TOOL_NAMES`, `READ_TOOL_NAMES`, and `detect_resources()` first.
- **Do not absorb selfloopbash's GitNexus invocation as-is.** AIDS currently has built-in file impact analysis plus external GitNexus fallback. The local GitNexus CLI currently requires explicit `--repo aids-tools` when multiple repos are indexed, so any future external call should pass repo context or use the already implemented built-in impact path.
- **Do not make SQLite failures block tool execution.** Ledger persistence is observability infrastructure; safety blocking should come from the in-memory/current-file hash decision path and should fail open only when the runtime cannot support blocking, per `docs/hook-contract.md`.

## Proposed implementation order

1. Add failing tests for missing-read and stale-read blocking.
2. Implement JSONL-backed `last_read_trace()` and `pre_write_decision()` in `bin/selftools`.
3. Wire `cmd_hook_pre_tool_use()` to block/warn according to policy.
4. Add policy metadata to traces in `cmd_hook_post_tool_use()`.
5. Add optional SQLite sidecar schema and mirror writes.
6. Switch `op-chain`/`query` to prefer SQLite chain output when available.
7. Backfill/migration command only after parity tests pass.
