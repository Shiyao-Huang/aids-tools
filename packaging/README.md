# AIDS packaging

This folder records the installable package surface for `aids-tools`.

Smoke-tested flows:

```sh
./install.sh --source . --install-dir "$tmp/install" --data-dir "$tmp/data" \
  --bin-dir "$tmp/bin" --claude-home "$tmp/home/.claude" --codex-home "$tmp/home/.codex"

bash -n install.sh hooks/*.sh wrappers/*
python3 -m py_compile bin/selftools bin/selftools-mcp
```

The public commands are `aids`, `aids-mcp`, `aids-run`, and `aids-bash`. Legacy aliases (`aid`, `selftools`, `AID_*`, `SELFTOOLS_*`, `ZHUYI_*`) remain supported for migration.

The installer is idempotent: reruns remove prior AIDS/selftools hook handlers before re-adding them, and the Codex MCP table is wrapped in marker comments for clean replacement/removal.
