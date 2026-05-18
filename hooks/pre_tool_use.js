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

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');
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
  const agentId = resolveAgentId(identity);

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
    injectBashContext(identity, toolInput.command || '', runtime, actorType, agentId);
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
 * Resolve agent_id: env var → session file → compute from identity fields.
 */
function resolveAgentId(identity) {
  const fromEnv = process.env.AIDS_AGENT_ID ||
                  process.env.AID_AGENT_ID ||
                  process.env.SELFTOOLS_AGENT_ID ||
                  process.env.ZHUYI_AGENT_ID;
  if (fromEnv) return fromEnv;

  if (identity.session_id && identity.session_id !== 'unknown') {
    try {
      const sessionPath = path.join(os.homedir(), '.aids', 'sessions', `${identity.session_id}.json`);
      if (fs.existsSync(sessionPath)) {
        const record = JSON.parse(fs.readFileSync(sessionPath, 'utf-8'));
        if (record.agent_id) return record.agent_id;
      }
    } catch { /* fall through */ }
  }

  const input = `${identity.display_name || ''}:${identity.role || ''}:${identity.team_id || ''}`;
  return 'agent-' + crypto.createHash('sha256').update(input).digest('hex').slice(0, 16);
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
 * Parse Bash command to detect file-mutation patterns and read targets.
 * Returns array: [bash:hash, ...parsedFilePaths].
 */
function extractBashResources(command) {
  if (!command) return [];
  const crypto = require('crypto');
  const path = require('path');
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

  // Detect read-only file targets: cat grep head tail wc sort uniq sed(without -i) etc.
  const readCmds = new Set([
    'cat', 'head', 'tail', 'less', 'more', 'wc', 'sort', 'uniq',
    'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack',
    'sed', 'awk', 'diff', 'comm', 'cut', 'tr',
    'file', 'stat', 'md5sum', 'sha256sum', 'sha1sum', 'shasum',
    'strings', 'hexdump', 'xxd', 'od',
  ]);
  const valueFlags = new Set([
    '-e', '--regexp', '-f', '--file', '-n', '--lines', '-c', '--bytes',
    '-k', '--key', '-t', '--field-separator', '-o', '--output',
    '-F', '-v', '-d', '--delimiter', '--label', '-L', '-U', '--unified',
    '-i', '--in-place',
  ]);
  const specialPaths = new Set(['/dev/null', '/dev/zero', '/dev/random', '/dev/urandom', '-']);
  const knownFiles = new Set([
    'Makefile', 'Dockerfile', 'README', 'LICENSE', 'CHANGELOG',
    'Rakefile', 'Gemfile', 'Vagrantfile', 'Jenkinsfile',
  ]);

  for (const segment of command.split('|')) {
    const tokens = segment.trim().split(/\s+/);
    if (!tokens.length) continue;
    const base = path.basename(tokens[0]);
    if (!readCmds.has(base)) continue;
    if (base === 'sed' && tokens.some(t => t === '-i' || /^-[^e]*i/.test(t))) continue;
    let skip = false;
    for (const tok of tokens.slice(1)) {
      if (skip) { skip = false; continue; }
      if (tok === ';' || tok === '&&' || tok === '||') break;
      if (valueFlags.has(tok)) { skip = true; continue; }
      if (tok.startsWith('-')) continue;
      if (specialPaths.has(tok)) continue;
      if (tok.includes('/') || tok.includes('.') || knownFiles.has(tok)) {
        try { results.push(normalizeFilePath(tok)); } catch { /* skip */ }
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

function injectBashContext(identity, command, runtime, actorType, agentId) {
  if (!command) return;
  const short = command.length > 60 ? command.slice(0, 57) + '...' : command;
  process.stderr.write(
    `AIDS pre-bash | ${runtime}/${actorType} | ${identity.role}/${identity.session_id.slice(0, 8)} | agent_id=${agentId} | ${short}\n`
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
