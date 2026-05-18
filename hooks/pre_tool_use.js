#!/usr/bin/env node
/**
 * AIDS (Agent-ID System) — PreToolUse Hook
 *
 * Runs BEFORE any tool call in Claude Code / Codex / Bash.
 * For Write/Edit: reads trace store for recent activity on target file,
 * injects warning/context if another session recently touched it.
 * For Bash: parses command for file-mutation patterns, applies write gates.
 *
 * Claude Code hook protocol:
 *   - Receives JSON on stdin: { tool_name, tool_input }
 *   - stderr output is shown to the agent as context
 *   - exit 0 = allow, exit 2 = block
 *
 * Env vars (primary AIDS_*, legacy aliases accepted):
 *   AIDS_SESSION_ID, AIDS_ROLE, AIDS_INTENT, AIDS_RUNTIME, AIDS_ACTOR_TYPE
 */

const { resolve } = require('../lib/session');
const { getRecentTraces, normalizeFilePath, TRACE_OPERATIONS } = require('../src/trace/trace');

const WRITE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'apply_patch', 'ApplyPatch']);
const RECENT_OPS_LIMIT = budgetInt('AIDS_RECENT_LIMIT', 3, 1, 20);
const CONTEXT_LINE_BUDGET = budgetInt('AIDS_AWARENESS_LINES', 8, 3, 40);
const CONTEXT_CHAR_BUDGET = budgetInt('AIDS_AWARENESS_CHARS', 140, 60, 500);

// --- Read stdin, then process ---

let inputData = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', (chunk) => { inputData += chunk; });
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(inputData);
    handle(input);
  } catch {
    process.exit(0);
  }
});

function handle(input) {
  const toolName = input.tool_name || '';
  const toolInput = input.tool_input || {};
  const identity = resolve();
  const runtime = inferRuntime();
  const actorType = inferActorType(runtime);

  if (!TRACE_OPERATIONS.has(toolName)) {
    process.exit(0);
  }

  const resourceKeys = extractResourceKeys(toolName, toolInput);
  if (resourceKeys.length === 0) {
    process.exit(0);
  }

  // Write/Edit/Bash-mutation: inject read-before-write context for file targets
  if (WRITE_TOOLS.has(toolName)) {
    for (const key of resourceKeys) {
      injectWriteContext(identity, key, runtime, actorType);
    }
  } else if (toolName === 'Bash' && resourceKeys.some(k => !k.startsWith('bash:'))) {
    for (const key of resourceKeys) {
      if (!key.startsWith('bash:')) {
        injectWriteContext(identity, key, runtime, actorType);
      }
    }
  }

  // Bash: lightweight command context
  if (toolName === 'Bash') {
    injectBashContext(identity, toolInput.command || '', runtime, actorType);
  }

  process.exit(0);
}

function inferRuntime() {
  return process.env.AIDS_RUNTIME ||
         process.env.AID_RUNTIME ||
         process.env.SELFTOOLS_RUNTIME ||
         process.env.ZHUYI_RUNTIME ||
         'unknown';
}

function inferActorType(runtime) {
  const explicit = process.env.AIDS_ACTOR_TYPE ||
                   process.env.AID_ACTOR_TYPE ||
                   process.env.SELFTOOLS_ACTOR_TYPE ||
                   process.env.ZHUYI_ACTOR_TYPE;
  if (explicit) return explicit;
  if (runtime === 'claude' || runtime === 'codex') return 'agent';
  if (runtime === 'bash') return process.env.AIDS_SESSION_ID ? 'human' : 'bash';
  return 'unknown';
}

/**
 * Extract stable resource keys from tool input.
 * File tools → [file path]. Bash → [bash:hash] + parsed file paths.
 */
function extractResourceKeys(toolName, toolInput) {
  if (toolName === 'Bash') {
    return extractBashResources(toolInput.command || '');
  }
  const fp = toolInput.file_path || toolInput.path || '';
  return fp ? [fp] : [];
}

/**
 * Parse Bash command to detect file-mutation patterns.
 * Returns array: [bash:hash, ...parsedFilePaths].
 */
function extractBashResources(command) {
  if (!command) return [];
  const crypto = require('crypto');
  const results = [];
  const hash = crypto.createHash('sha256').update(command).digest('hex').slice(0, 16);
  results.push(`bash:${hash}`);

  // Detect file-mutation targets: > >> tee mv cp
  const patterns = [
    />\s*["']?([^"'\s;|&]+)/g,
    />>\s*["']?([^"'\s;|&]+)/g,
    /tee\s+["']?([^"'\s;|&]+)/g,
    /\b(?:mv|cp)\s+["']?[^"'\s]+["']?\s+["']?([^"'\s;|&]+)/g,
  ];
  for (const pat of patterns) {
    let m;
    while ((m = pat.exec(command)) !== null) {
      const target = m[1] || m[m.length - 1];
      if (target && !target.startsWith('-')) {
        try { results.push(normalizeFilePath(target)); } catch { /* skip */ }
      }
    }
  }

  return results;
}

function injectWriteContext(identity, resourceKey, runtime, actorType) {
  const isBash = resourceKey.startsWith('bash:');
  let recentTraces;
  try {
    recentTraces = isBash ? [] : getRecentTraces(resourceKey, RECENT_OPS_LIMIT);
  } catch {
    return;
  }
  if (recentTraces.length === 0) return;

  const otherTraces = recentTraces.filter(
    (t) => (t.sessionId || t.session_id) !== identity.session_id
  );
  if (otherTraces.length === 0) return;

  const label = isBash ? `bash command ${resourceKey}` : resourceKey;
  const lines = [
    '',
    '━━━ AIDS (Agent-ID System) — 操作上下文 ━━━',
    `⚠️  ${label} was recently modified by other sessions:`,
    '',
  ];

  for (const t of otherTraces) {
    const ago = formatAgo(t.timestamp);
    const sid = (t.sessionId || t.session_id || '').slice(0, 8);
    const who = `${t.role || 'unknown'}/${sid}`;
    const runt = t.runtime ? ` [${t.runtime}]` : '';
    const actor = t.actor_type ? ` (${t.actor_type})` : '';
    const why = t.purpose ? ` — ${clip(t.purpose)}` : '';
    lines.push(`  • ${t.operation} by ${who}${runt}${actor}${why} (${ago})`);
  }

  lines.push('');
  lines.push('Verify your changes do not conflict with the above.');
  lines.push('━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  lines.push('');
  process.stderr.write(budgetLines(lines).join('\n'));
}

function injectBashContext(identity, command, runtime, actorType) {
  if (!command) return;
  const short = command.length > 60 ? command.slice(0, 57) + '...' : command;
  process.stderr.write(
    `AIDS pre-bash | ${runtime}/${actorType} | ${identity.role}/${identity.session_id.slice(0, 8)} | ${short}\n`
  );
}

function budgetInt(name, fallback, min, max) {
  const parsed = Number(process.env[name] || process.env[name.replace('AIDS_', 'AID_')] || fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(parsed)));
}

function clip(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= CONTEXT_CHAR_BUDGET) return text;
  return text.slice(0, CONTEXT_CHAR_BUDGET - 1).trimEnd() + '…';
}

function budgetLines(lines) {
  if (lines.length <= CONTEXT_LINE_BUDGET) return lines;
  const hidden = lines.length - CONTEXT_LINE_BUDGET + 1;
  return lines.slice(0, CONTEXT_LINE_BUDGET - 1).concat(`  • ${hidden} context lines clipped; use aids trace/recent tools to expand.`);
}

function formatAgo(ts) {
  let diffMs;
  try { diffMs = Date.now() - new Date(ts).getTime(); } catch { return '?'; }
  if (diffMs < 60000) return `${Math.floor(diffMs / 1000)}s ago`;
  if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
  return `${Math.floor(diffMs / 3600000)}h ago`;
}
