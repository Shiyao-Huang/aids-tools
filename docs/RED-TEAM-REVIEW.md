# AIDS Design Red-Team Review

Purpose: challenge each new AIDS design before implementation hardens. This is not a replacement design doc; it is a failure-oriented review. Each section asks the sharp question, names a plausible failure scenario, explains why the current design may not withstand it, and lists required fixes / acceptance tests.

Review stance: storage must preserve evidence; compact output may summarize but must disclose what was hidden and how to retrieve it.

## 1. `aids q` Aggregated Query

**Sharp question:** Does a low-friction query router actually reduce tool calls, or does it secretly call every expensive resolver and hide critical audit details in compact mode?

**Failure scenario**
- A user runs `aids q README.md` before editing.
- The router invokes identity + history + signature + impact + ratings every time.
- GitNexus is slow or errors, grep fallback scans too much, and compact output shows only “2 recent traces” while hiding a bad rating or failed signature.
- The agent trusts the compact result and edits a high-risk file.

**Why the current design may not withstand it**
- Resolver fan-out can increase latency/tool cost if every module runs by default.
- Compact formatting can become a lossy audit surface if it does not show hidden counts, risk flags, and next commands.
- Include/exclude exists, but default module choice is a policy decision; if config is malicious or overly broad, “low input” becomes “high hidden work.”

**Suggested fix**
- Add per-resolver timeout/budget and mark partial results explicitly.
- Default compact output must always surface high-risk facts: failed signature, bad rating, high impact, most recent writer, and resolver errors.
- Add hidden counters and progressive disclosure commands, e.g. `hidden: history+12 impact+8; more: aids q README.md --full`.
- Cache expensive impact results with TTL and source metadata.

**Minimum acceptance tests**
- Disable `impact` in config and prove it is not executed.
- Simulate GitNexus failure; compact output must show `impact:error` or `impact:fallback`, not silently omit it.
- Seed bad rating + failed signature + many traces; compact output must still show the bad/failed facts.
- Assert compact output stays under configured char budget and reports hidden counts.

## 2. `aids sign` Signature Chain

**Sharp question:** Does `hash_chain` over JSONL actually raise forge cost, or can any agent edit one JSONL row and recompute downstream hashes?

**Failure scenario**
- A malicious or buggy agent modifies an old trace JSONL line and recomputes `signature_hash` fields for later rows.
- There is no external anchor, append-only file protection, key separation, or signed checkpoint.
- `aids verify` passes because it only checks internal consistency.

**Why the current design may not withstand it**
- A self-contained hash chain only detects accidental corruption, not a writer who can rewrite the whole file.
- JSONL has low forge cost if file permissions are broad and there are no checkpoints.
- SQLite ledger helps indexing but does not itself prevent rewrite unless configured with append-only/WAL/anchors.

**Suggested fix**
- Separate “integrity chain” from “tamper resistance.” Document threat model.
- Add periodic anchored checkpoints: daily root hash in separate file, git commit, OS keychain signature, or remote append-only sink.
- Store `prev_signature_hash`, `signature_hash`, canonicalized payload, strategy name, and verifier version.
- Make signature backend pluggable: `none`, `hash_chain`, `sqlite_ledger`, `external_anchor`.
- `verify` must report forge-cost level, not just pass/fail.

**Minimum acceptance tests**
- Mutate one old JSONL trace and verify fails.
- Recompute local chain without checkpoint and verify reports “internally consistent but unanchored,” not “trusted.”
- Remove/disable signature via config and doctor flags it as reduced assurance.
- SQLite backend and JSONL backend produce comparable verification results for same trace set.

## 3. `aids impact`

**Sharp question:** If GitNexus is unavailable, stale, or wrong repo is selected, is grep fallback good enough to prevent false confidence?

**Failure scenario**
- `aids impact bin/selftools` hits “Multiple repositories indexed” or stale GitNexus data.
- Grep fallback finds only string references, misses dynamic invocation, shell wrappers, install scripts, and generated symlinks.
- Output says LOW because dependent count is small, but the file is actually the primary CLI entrypoint.

**Why the current design may not withstand it**
- Grep dependents are not semantic impact analysis.
- Risk scoring based only on dependent count ignores file centrality, executable status, install references, hook usage, and test coverage.
- GitNexus errors can be confused with low-risk summaries unless normalized.

**Suggested fix**
- Auto-resolve repo (`--repo aids-tools`) or retry on multi-repo error.
- Impact result must include source status: `gitnexus:fresh`, `gitnexus:stale`, `grep:fallback`, `error`.
- Add heuristics for executable CLI files, hook scripts, install payload, symlink targets, and files named in tests.
- Risk must degrade to UNKNOWN/MEDIUM on stale/error, never LOW by absence of evidence.

**Minimum acceptance tests**
- Mock multi-repo GitNexus error; command retries with repo or reports fallback explicitly.
- Nonexistent file returns clear exit 1.
- `bin/selftools` is never LOW if GitNexus is unavailable.
- Grep fallback output includes limitations and inspected scope.

## 4. Stable `agent_id` Across Sessions

**Sharp question:** Is `hash(display_name + role + team_id)` a stable identity, or does it merge two humans/agents who happen to share a name and role?

**Failure scenario**
- Two implementers both have display name “Agent implementer,” role `implementer`, same team, same repo.
- Hash fingerprint merges their history into one `agent_id`.
- Reputation, audit, and `aids q <agent_id>` now attribute actions to the wrong actor.

**Why the current design may not withstand it**
- Display name and role are labels, not identity proof.
- Team/task/project reduce collisions but do not eliminate them.
- If env/session/event IDs change, aliases can help, but alias merging can also permanently attach wrong identities.

**Suggested fix**
- Treat `agent_id` as an explicit registry record with confidence and evidence, not a pure deterministic hash.
- Fingerprint should include stable runtime provenance where available: AHA session lineage, spec/genome id, workspace, team id, user-approved alias, and first-seen timestamp.
- Alias merge must be reversible and auditable; require manual confirmation or high-confidence evidence when names collide.
- Store `actor_snapshot` in every trace so old history is not overwritten by later registry changes.

**Minimum acceptance tests**
- Two same-name/same-role agents on same team but different task/workspace do not auto-merge.
- Same agent restarted with same lineage/project does merge.
- Alias merge creates an audit event and can be undone.
- Query display uses trace `actor_snapshot` first, registry fallback second.

## 5. Adaptive Truncation / Progressive Disclosure

**Sharp question:** When compact mode trims content, how does an agent know what was removed and how to recover it before making a risky edit?

**Failure scenario**
- Compact output drops older history entries, long commands, and low-ranked impact references.
- The hidden entry is the only one showing a bad rating or destructive Bash command.
- The agent sees “compact OK” and proceeds.

**Why the current design may not withstand it**
- A char budget alone optimizes length, not audit value.
- “Risk weights” can be wrong or missing for new resolver types.
- If compact JSON drops fields instead of summarizing them, downstream agents cannot tell whether information is absent or hidden.

**Suggested fix**
- Store full evidence; only formatter truncates.
- Formatter must produce a disclosure footer: used/limit chars, hidden counts per module, risk flags hidden or shown, and exact `--more`/`--full` command.
- Critical facts are non-droppable: failed verify, bad rating, high/unknown impact, newest writer, current identity, resolver errors.
- Use module budgets as soft weights; reallocate unused budget and reserve an emergency risk budget.

**Minimum acceptance tests**
- Many long traces + one bad rating: compact still shows bad rating.
- Compact output includes `hidden` counts and `more` command.
- `--full` includes exact full command/intent/path that compact omitted.
- JSON compact distinguishes `hidden_count` from `count=0`.

## 6. `~/.aids/config.json`

**Sharp question:** If config controls signature, impact, hooks, and query modules, who is allowed to turn protections off?

**Failure scenario**
- A compromised agent edits `~/.aids/config.json` and disables `signature`, `impact`, or pretool warnings.
- Future traces are generated without protection, but output remains friendly/green.
- Uninstall/reinstall preserves malicious config because installer “does not overwrite existing config.”

**Why the current design may not withstand it**
- Config is both policy and local mutable data.
- “Do not overwrite” protects user customizations but also preserves compromised policy.
- Doctor may check syntax but not policy drift, provenance, or unsafe settings.

**Suggested fix**
- Split defaults, local preferences, and security policy:
  - packaged defaults
  - user config
  - optional locked policy / signed baseline
- Doctor must report unsafe settings and config mtime/owner/path.
- Security-critical disable operations should be explicit and visible in every command (`signature:disabled by config`).
- Installer should merge missing keys but warn on unsafe existing settings; uninstall should preserve data by default but remove hook activation.

**Minimum acceptance tests**
- Config disables signature; `aids q` and `doctor` both show degraded assurance.
- Invalid config falls back safely and emits warning.
- Existing config merge preserves user values but adds new defaults.
- Config file with world-writable permissions is flagged.

## 7. Install / Uninstall Lifecycle

**Sharp question:** After uninstall and reinstall, are old traces still readable, hooks not broken, config not silently downgraded, and CLI symlinks not stale?

**Failure scenario**
- User uninstalls. Claude/Codex hook config still points to a removed `selftools` path.
- Later a tool call fails because a hook executable is missing.
- User reinstalls; old `~/.aids` traces exist but config schema is old and new commands behave inconsistently.

**Why the current design may not withstand it**
- Install often focuses on copying binaries, not lifecycle migration.
- Hook configs, MCP blocks, wrappers, symlinks, data dir, config, and ledger are separate surfaces.
- Purge semantics can accidentally delete audit history or leave dangerous hooks.

**Suggested fix**
- Add explicit uninstall path with modes:
  - default: remove binaries/symlinks/hooks/MCP, preserve `~/.aids` data.
  - `--purge-data`: delete traces/sessions/ratings/config/ledger after confirmation.
  - `--dry-run`: show all actions.
- Install must run config migration and doctor checks after copying.
- Doctor must detect stale hook paths and stale symlinks.
- Reinstall must preserve and migrate old trace/config schemas.

**Minimum acceptance tests**
- Install then `aids q`, `aids impact`, `aids doctor` work from installed path.
- Uninstall removes hook references and symlinks; no missing executable hook remains.
- Reinstall with old `~/.aids/config.json` migrates missing query/signature/impact keys.
- `--purge-data` is the only path that removes trace history.

## Cross-cutting red-team requirements

1. Every new resolver/strategy must have: config key, disabled behavior, failure status, compact output, full output, and doctor check.
2. Every compact output must reveal hidden counts and recovery command.
3. Every security claim must state threat model and forge-cost level.
4. Every identity display must prefer immutable per-trace `actor_snapshot`; mutable registry is fallback only.
5. Every installer change must have uninstall and reinstall tests.
6. Every fallback must lower confidence, not silently report success.
