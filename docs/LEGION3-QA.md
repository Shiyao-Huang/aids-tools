# LEGION3-QA — Independent QA Report

**Date:** 2026-05-18
**QA Agent:** qa-engineer (Claude Sonnet 4.6)
**Scope:** AIDS core CLI, edge cases, query modes, invariant tests

---

## Executive Summary

| Category | Result |
|----------|--------|
| Existing test suite | **141/141 Python PASS** + **7/7 Node.js PASS** |
| Edge cases found | **1 P1 bug**, 0 P0, 2 P2 notes |
| Concurrent writes | **PASS** (10 procs x 5 traces = 50/50 unique, 0 corrupt) |
| Query modes | **8/8 PASS** |
| Invariant tests | **7/7 PASS** (INV-1 through INV-7) |

---

## Test Results

### 1. Existing Test Suite

- `python3 -m pytest tests/ -v`: **141 passed in 16.88s**
- `node --test tests/trace-ratings.test.js`: **7 passed in 270ms**
- Zero failures, zero skips.

### 2. Edge Case: Empty Trace/Rating Files

| Command | RC | Behavior |
|---------|-----|----------|
| `stats --json` | 0 | Returns `{"sessions":{"total":0},"traces":{"total":0},...}` |
| `timeline` | 1 | "No timeline events today." |
| `who-touched <path>` | 1 | "No AIDS traces for <path>" |
| `op-chain <path>` | 1 | "No AIDS traces for <path>" |
| `q <path> --json` | 0 | Returns structured response with `"status":"no_data"` |
| `rate tr_ghost good` | 1 | "Trace not found: tr_ghost" |
| `doctor --json` | 0 | Reports `all_ok: false` (expected: claude_settings missing in test env) |

**Verdict:** PASS. All commands handle empty data gracefully.

### 3. Edge Case: Long File Paths

**P1 BUG FOUND:** `aids q` crashes with `[Errno 63] File name too long` when given a path >255 chars.

- **Root cause:** `detect_query_target()` at line 1950 calls `load_session(tok)` for every query token before checking if it's a file path. `session_path()` constructs a filename from the raw token, which exceeds the OS filename limit (255 bytes on macOS/APFS).
- **Affected:** `aids q`, `aids query`, `aids ask` — all route through `detect_query_target`.
- **Not affected:** `who-touched`, `op-chain` — these use `load_index()` → `index_key()` which correctly hashes long paths.
- **Fix:** Add a length guard in `session_path()` (truncate the safe filename or hash it) or skip `load_session()` for tokens longer than a reasonable session_id length (~200 chars).

**Example:**
```
$ aids q /tmp/aaa...aaa/sub/bbb...bbb/file.py
aids error: [Errno 63] File name too long: '.../sessions/_tmp_aaa...file.py.json'
```

### 4. Edge Case: Concurrent Write Conflicts

- **Method:** 10 forked processes, each writing 5 trace records to the same JSONL file.
- **Result:** 50/50 records written, 50 unique trace_ids, 0 corrupt lines.
- **Verdict:** PASS. `append_jsonl` handles concurrent writes safely.

### 5. Edge Case: agent_id Collision

- `compute_agent_id(name, role, team_id)` is deterministic: same inputs produce same agent_id (by design for stable identity).
- Different inputs produce different agent_ids: verified 4 unique IDs from 5 inputs (1 intentional collision).
- `register_session()` reads display_name/role/team_id from environment variables, which can override event-provided values. This is intentional (env vars are the source of truth for hook-driven registration) but test authors should be aware.

**Verdict:** PASS (no accidental collisions). Note: env var precedence is documented behavior.

### 6. aids q Query Modes

| # | Query Mode | Input | RC | kind | Status |
|---|-----------|-------|-----|------|--------|
| 1 | File path | `/tmp/query_test.py` | 0 | `file` | PASS |
| 2 | Trace ID | `tr_query_test` | 0 | `trace` | PASS |
| 3 | Rating ID | `rt_q_1` | 0 | `rating` | PASS |
| 4 | Session ID | `q-sess-1` | 0 | `session` | PASS |
| 5 | Ask (text) | `who touched <path>` | 0 | `file` | PASS |
| 6 | Unknown | `random-unknown-thing` | 0 | `unknown` | PASS |
| 7 | Include/exclude | `--include history,ratings --exclude ratings` | 0 | modules=`["history"]` | PASS |
| 8 | Alias | `q` == `query` | 0 | identical results | PASS |

---

## Bug Summary

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| QA-1 | **P1** | `aids q` crashes on paths >255 chars due to `session_path()` filename length | Open |
| QA-2 | P2 | `doctor --json` reports `all_ok: false` when `~/.claude/settings.json` doesn't exist — cosmetic only | By design |
| QA-3 | P2 | `register_session` env var precedence may surprise test authors | Documented |

---

## Recommendations

1. **Fix QA-1:** Add length guard in `session_path()` — if `len(safe) > 200`, use `sha256(safe)[:40]` as filename. This is consistent with how `index_key()` handles long resources.
2. **Add edge case tests:** The long-path crash should have a regression test.
3. **Consider a query target pre-filter:** Before calling `load_session(tok)`, check if `tok` looks like a plausible session ID (length, prefix, character set) to avoid unnecessary filesystem operations.

---

## Test Environment

- **OS:** macOS Darwin 25.5.0 (APFS)
- **Python:** 3.9.6
- **Node.js:** available (trace-ratings.test.js passes)
- **Test data:** All tests use `tempfile.mkdtemp()` — isolated, cleaned up after each test
