# AIDS install instructions

> **Status:** Implemented locally in `install.sh`; public GitHub URL remains a placeholder until the repository is pushed.

## One-line install (placeholder URL until publish)

```sh
# Placeholder org/repo until publish.
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aids-tools/main/install.sh | bash
```

The installer:

1. Detect whether the host has Claude Code, Codex, or both.
2. Drop the AIDS tool wrappers into the right hook directories for each runtime.
3. Register a session ID provider so every tool call carries an attributed badge.
4. Wire the write-after-read hook so any `Write`/`Edit` surfaces prior actors first.
5. Be **idempotent** — re-running upgrades in place without duplicating hooks.
6. Prints a one-screen post-install summary: which runtimes were touched, where hooks live, how to disable.

## Reference installers

The user explicitly cited these as the shape to mirror:

- **superpower** — for the overall ergonomics of a one-command bootstrap.
- **claude-for-codex** — the canonical curl-pipe pattern:

  ```sh
  curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/claude-for-codex/main/install.sh | bash
  ```

## Manual install (planned fallback)

When the curl-pipe path is unsuitable (air-gapped, audit-required, suspicious of `| bash`), the installer must support:

```sh
git clone https://github.com/Shiyao-Huang/aids-tools
cd aids-tools
./install.sh
```

Both paths converge on the same hook registration.

## Uninstall

The installer ships `./install.sh --uninstall`, which:

- Removes every hook it added.
- Leaves user-authored hooks untouched.
- Reports what was removed.

## Verification checklist (post-install)

A successful install should be verifiable by running:

```sh
aids doctor
```

- Session ID provider: ✅ / ✗
- Write-after-read hook: ✅ / ✗
- Claude Code integration: ✅ / ✗
- Codex integration: ✅ / ✗
- `gitnexus` link: ✅ / ✗

## Provenance

- Tracked under Kanban task: `RJB41asLxowC` ("AIM").
- Owning roles: builder + framer (implementation), scribe (this doc).
- Vision context: `../VISION.md`.
