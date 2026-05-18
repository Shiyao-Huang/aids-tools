# Legion5 QA Report — Independent Verification

**QA Agent:** Legion5 Codex QA (qa-engineer/claude)
**Date:** 2026-05-18
**Scope:** Legion5 unstaged changes in `bin/selftools` + `tests/test_selftools.py`
**Baseline commit:** `d83adf2` (Legion4)

---

## Summary

Legion5 adds **identity disclosure enrichment** and **smart stale-lock detection**. The changes are functionally correct and well-tested. One P1 bug found in CSV export (pre-existing, not caused by Legion5). Several P2 feature gaps noted.

**Overall Verdict: PASS WITH ISSUES** — safe to merge after P1 CSV fix.

---

## Changes Under Test

| Change | Description | Status |
|--------|-------------|--------|
| `identity_lines()` | New helper: generates 3-line identity disclosure | PASS |
| Session-start hook | Now includes `model` + `agent_id` in registration message | PASS |
| PostToolUse hook | Every trace output now appends full identity lines | PASS |
| `_compact_trace()` | New fields: `display_name`, `model` | PASS |
| `cmd_doctor` stale locks | Smart detection: PID-alive check + STALE_SECONDS instead of counting all .lock files | PASS |
| `TestIdentityDisclosure` | 2 new unit tests for identity_lines + _compact_trace | PASS |

---

## Test Results

### 1. pytest (Full Suite)
- **118/118 PASSED** in 3.20s
- All existing tests still green; no regressions

### 2. CLI Commands

| Command | Result | Notes |
|---------|--------|-------|
| `export --format json --type all` | PASS | 18.7MB export, valid JSON |
| `export --format jsonl --type sessions` | PASS | 149 sessions, valid JSONL |
| `export --format csv --type traces` | **P1 BUG** | Column headers duplicated (agent_id x200+, chain_hash x200+, model x200+) |
| `export --output /tmp/...` | PASS | File write works |
| `stats --all --json` | PASS | by_role + by_runtime breakdowns correct |
| `impact bin/selftools` | PASS | Shows importance/risk/dependents/traces |
| `commit-stamp` | PASS | Correct Co-Authored-By with session identity |
| `doctor` | PASS | 23/23 checks green, smart stale lock count (0 stale / 33 total) |
| `verify` | **P2** | 8 CHAIN BROKEN (all Codex concurrent writes, pre_hash=None) |

### 3. aids verify — Chain Integrity
- **1903/1911 traces OK** (99.6%)
- 8 broken chains, all in `2026-05-18.jsonl`, all from **Codex runtime** agents
- Root cause: concurrent cross-runtime trace writes (pre_hash=None indicates chain not properly linked)
- **Not caused by Legion5 changes** — pre-existing concurrency issue

### 4. Identity Disclosure
- `identity_lines()` produces correct 3-line output
- `_compact_trace()` preserves `display_name` and `model`
- Both covered by `TestIdentityDisclosure` unit tests

---

## Issues Found

### P1 — CSV Export Column Duplication
- **File:** `bin/selftools` (CSV export path)
- **Symptom:** CSV header has `agent_id`, `chain_hash`, `model`, `result` columns repeated hundreds of times
- **Cause:** Likely the CSV writer adds one column per trace record instead of normalizing to unique columns
- **Impact:** CSV export is unusable for analysis
- **JSON/JSONL formats unaffected**

### P2 — `stats` Missing `--by-agent` Breakdown
- **Symptom:** `stats --all --json` returns `by_role` and `by_runtime` but no `by_agent`
- **No `--by-agent` CLI flag exists**
- The `agent_id` field is available in session data, so aggregation is feasible

### P2 — `doctor --clean-locks` Not Implemented
- **Symptom:** `doctor --help` shows only `--json`, no `--clean-locks` flag
- The improved stale detection logic works well but there's no way to clean stale locks via CLI

### P2 — Chain Breaks from Codex Concurrent Writes
- **8 CHAIN BROKEN** traces in today's data, all from Codex runtime
- `pre_hash=None` suggests chain linking not working under concurrent writes
- Pre-existing issue, not caused by Legion5

---

## Recommendations

1. **Fix CSV export column duplication before merge** (P1)
2. Add `--by-agent` to `stats` command (P2, can defer)
3. Add `doctor --clean-locks` to remove stale lock files (P2, can defer)
4. Investigate Codex concurrent write chain integrity (P2, separate task)

---

## Test Environment

- **Platform:** Darwin 25.5.0 (macOS)
- **Python:** system python3
- **Data dir:** `~/.aids`
- **Test data:** 1911 traces, 149 sessions, 1243 unique resources, 5 ratings
- **Lock mechanism:** fcntl.flock
