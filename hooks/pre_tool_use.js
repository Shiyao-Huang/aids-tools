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
 */

const { resolve } = require('../lib/session');
const { getRecentTraces, normalizeFilePath, TRACE_OPERATIONS } = require('../src/trace/trace');
const {
  inferRuntime, inferActorType, resolveAgentId,
  extractResourceKeys, budgetInt, formatAgo, clip, budgetLines,
} = require('./_aid_shared');

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
    const why = t.purpose ? ` — ${clip(t.purpose, CONTEXT_CHAR_BUDGET)}` : '';
    lines.push(`  • ${t.operation} by ${who}${runt}${actor}${why} (${ago})`);
  }

  lines.push('');
  lines.push('Verify your changes do not conflict with the above.');
  lines.push('━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  lines.push('');
  process.stderr.write(budgetLines(lines, CONTEXT_LINE_BUDGET).join('\n'));
}

function injectBashContext(identity, command, runtime, actorType, agentId) {
  if (!command) return;
  const short = command.length > 60 ? command.slice(0, 57) + '...' : command;
  process.stderr.write(
    `AIDS pre-bash | ${runtime}/${actorType} | ${identity.role}/${identity.session_id.slice(0, 8)} | agent_id=${agentId} | ${short}\n`
  );
}
