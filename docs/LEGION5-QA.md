# Legion5 QA Report — Full Regression + Edge Cases

**QA Agent:** Legion5 Codex QA (qa-engineer/claude)
**Date:** 2026-05-18
**Scope:** Legion5 full regression: all subcommands, edge cases, cross-validation
**Baseline commit:** `d83adf2` (Legion4)
**Task:** RrpT55zQ7bEl

---

## Summary

Legion5 adds **identity disclosure enrichment**, **smart stale-lock detection**, **`doctor --clean-locks`**, **`export` command**, **`stats` aggregation**, and **`impact` analysis**. Full regression found **2 P1 bugs** (one new, one pre-existing) and several P2 issues.

**Overall Verdict: FAIL — 2 test regressions, 1 P1 bug must be fixed before merge.**

---

## Changes Under Test (vs Legion4 baseline)

| Change | Description | Status |
|--------|-------------|--------|
| `identity_lines()` | New helper: generates 3-line identity disclosure | PASS |
| Session-start hook | Now includes `model` + `agent_id` in registration message | PASS |
| PostToolUse hook | Every trace output now appends full identity lines | PASS |
| `_compact_trace()` | New fields: `display_name`, `model` | PASS |
| `cmd_doctor` stale locks | Smart detection: PID-alive check + STALE_SECONDS | BUG (see P1 #2) |
| `doctor --clean-locks` | New flag to remove stale locks | BUG (see P1 #2) |
| `cmd_export` | Export traces/sessions/ratings/timeline in JSON/JSONL/CSV | BUG (see P1 #1) |
| `cmd_stats` | Aggregated statistics with by_role/by_runtime | PASS |
| `cmd_impact` | File impact analysis with dependents/risk | PASS |
| `cmd_commit_stamp` | Git Co-Authored-By trailer with identity | PASS |
| New unit tests | identity_lines, _compact_trace, export, stats, infer_runtime, infer_actor_type, agent_id backfill | 145/147 PASS (2 fail) |

---

## Test Results

### 1. pytest (Full Regression)
- **145/147 PASSED, 2 FAILED** in 4.22s
- **Regressions:**
  - `TestCmdDoctor::test_doctor_clean_locks_removes_stale` — FAIL
  - `TestCmdDoctor::test_doctor_without_clean_locks_no_deletion` — FAIL
- All other 145 tests pass including new export, stats, infer_runtime, infer_actor_type, agent_id backfill tests

### 2. CLI Commands — All Subcommands

| Command | Result | Notes |
|---------|--------|-------|
| `export --format json --type all` | PASS | Valid JSON, ~25MB |
| `export --format jsonl --type sessions` | PASS | 181 sessions, valid JSONL |
| `export --format csv --type traces` | **P1 BUG** | Column headers duplicated (agent_id x200+, chain_hash x200+) |
| `export --output FILE` | PASS | File write works |
| `export --from DATE --to DATE` | PASS | Date range filter correct (1 trace for 2026-05-17) |
| `export --session ID` | PASS | Session filter correct (104 traces) |
| `export --format jsonl --type traces` | PASS | JSONL traces valid |
| `stats --all --json` | PASS | by_role + by_runtime + by_status + top_sessions correct |
| `impact bin/selftools` | PASS | Shows importance/risk/dependents/traces |
| `commit-stamp` | PASS | Correct Co-Authored-By with session identity |
| `doctor` | PASS | All checks green, smart stale lock count (0 stale / 52 total) |
| `doctor --clean-locks` | PASS (CLI) | Flag accepted, but see P1 #2 for functional bug |
| `verify` | **P2** | 14 CHAIN BROKEN (Codex concurrent writes) |
| `rate ID good "comment"` | PASS | Special chars (中文/quotes) handled |
| `who-touched NONEXISTENT` | PASS | Graceful exit 1 |
| `session-info NONEXISTENT` | PASS | Graceful "No session found", exit 1 |
| `ask "random query"` | PASS | Graceful unknown handling |
| `q "nonexistent-file"` | PASS | Graceful unknown handling |
| `timeline` | PASS | Lists recent events |
| `register-session` | PASS | Session creation works |
| `list-sessions` | PASS | Lists all sessions |

### 3. Edge Cases

| Test | Result | Notes |
|------|--------|-------|
| Empty data dir (export) | N/A | `SELFTOOLS_DATA_DIR` not fully respected in CLI subprocess |
| Chinese + special chars in rate comment | PASS | Correctly stored and returned |
| Date range filter (export) | PASS | Only matching traces returned |
| Session filter (export) | PASS | Correct count |
| Nonexistent file (who-touched) | PASS | Graceful "No traces", exit 1 |
| Nonexistent session (session-info) | PASS | Graceful "No session found", exit 1 |
| Unknown query (ask/q) | PASS | No crash, graceful output |

### 4. Cross-Validation

| Metric | stats | verify | Consistent? |
|--------|-------|--------|-------------|
| Total traces | 2,335 | 2,332 verified | Minor variance (ongoing writes during test) |
| Total sessions | 181 | — | — |
| Timeline events | 2,341 | — | Consistent with trace count |
| Chain integrity | — | 14 broken / 2,318 OK | 99.4% OK |

### 5. aids verify — Chain Integrity
- **2,318/2,332 traces OK** (99.4%)
- 14 broken chains in `2026-05-18.jsonl`, all from **Codex runtime** agents
- Root cause: concurrent cross-runtime trace writes (`pre_hash=None`)
- **Not caused by Legion5 changes** — pre-existing concurrency issue

---

## Issues Found

### P1 #1 — CSV Export Column Duplication
- **File:** `bin/selftools` (CSV export path in `cmd_export`)
- **Symptom:** CSV header has `agent_id`, `chain_hash`, `model`, `result` columns repeated hundreds of times
- **Cause:** CSV DictWriter likely writes one column per record key instead of deduplicating
- **Impact:** CSV export is unusable for data analysis
- **Workaround:** Use `--format json` or `--format jsonl` instead
- **JSON/JSONL formats unaffected**

### P1 #2 — `ensure_layout()` Eagerly Deletes Stale Locks (2 test regressions)
- **File:** `bin/selftools:118` — `ensure_layout()` calls `clean_all_stale_locks()` unconditionally
- **Symptom:** `doctor` command's stale-lock detection always finds 0 stale locks because `ensure_layout()` already deleted them
- **Failing tests:**
  - `TestCmdDoctor::test_doctor_clean_locks_removes_stale` — expects `clean_locks` check in result but stale_locks is empty
  - `TestCmdDoctor::test_doctor_without_clean_locks_no_deletion` — stale lock deleted by `ensure_layout()` before doctor's own check
- **Root cause chain:** `cmd_doctor()` → `ensure_layout()` → `clean_all_stale_locks()` → deletes all stale locks → doctor's own stale detection finds nothing
- **Impact:** `doctor` stale lock reporting is always clean; `--clean-locks` flag has no visible effect
- **Recommended fix:** Remove `clean_all_stale_locks()` from `ensure_layout()`, only call it from `doctor --clean-locks` or an explicit cleanup command

### P2 #1 — `stats` Missing `by_agent` Aggregation
- **Symptom:** `stats --all --json` returns `by_role` and `by_runtime` but no `by_agent`
- `agent_id` field available in sessions, aggregation is feasible

### P2 #2 — Chain Breaks from Codex Concurrent Writes
- **14 CHAIN BROKEN** traces, all from Codex runtime
- `pre_hash=None` suggests chain linking broken under concurrent writes
- Pre-existing issue, not caused by Legion5

### P2 #3 — `SELFTOOLS_DATA_DIR` Not Fully Respected
- Setting `SELFTOOLS_DATA_DIR` to empty dir via CLI env still reads from `~/.aids`
- Unit tests work because they import `selftools` directly and set env before calling
- CLI subprocess may have caching or import-time resolution issue

---

## Recommendations

1. **[BLOCKING] Fix P1 #2: Remove `clean_all_stale_locks()` from `ensure_layout()`** — This fixes 2 test regressions and makes `doctor --clean-locks` functional
2. **[BLOCKING] Fix P1 #1: CSV export column deduplication** — Use explicit fieldnames in CSV DictWriter
3. Add `by_agent` aggregation to `stats` (P2, can defer)
4. Investigate Codex concurrent write chain integrity (P2, separate task)
5. Investigate `SELFTOOLS_DATA_DIR` CLI env handling (P2)

---

## Test Environment

- **Platform:** Darwin 25.5.0 (macOS)
- **Python:** 3.9.6 (system)
- **Data dir:** `~/.aids`
- **Test data at time of report:** 2,335 traces, 181 sessions, 1,464 unique resources, 5 ratings
- **Lock mechanism:** fcntl.flock (52 lock files, 0 stale)
