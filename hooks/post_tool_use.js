#!/usr/bin/env node
/**
 * AIDS (Agent-ID System) — PostToolUse Hook
 *
 * Runs AFTER any tool call in Claude Code / Codex / Bash.
 * Records TraceRecords with actor_type, runtime, resource_key via the
 * full-featured src/trace/trace.js (includes timeline events + index updates).
 * Also handles Bash commands by parsing file-mutation patterns.
 *
 * Claude Code hook protocol:
 *   - Receives JSON on stdin: { tool_name, tool_input, tool_result }
 *   - stderr output is shown to the agent
 *   - exit 0 = pass through
 *
 * Env vars (primary AIDS_*, legacy aliases accepted):
 *   AIDS_SESSION_ID, AIDS_ROLE, AIDS_INTENT, AIDS_RUNTIME, AIDS_ACTOR_TYPE
 */

const crypto = require('crypto');
const { resolve } = require('../lib/session');
const { appendTrace, normalizeFilePath, TRACE_OPERATIONS } = require('../src/trace/trace');

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

  if (!TRACE_OPERATIONS.has(toolName)) {
    process.exit(0);
  }

  const identity = resolve();
  const runtime = inferRuntime();
  const actorType = inferActorType(runtime);

  // Extract resource keys (may be multiple for Bash with file mutations)
  const resourceKeys = extractResourceKeys(toolName, toolInput);
  if (resourceKeys.length === 0) {
    process.exit(0);
  }

  // Record a trace for each resource key
  for (const key of resourceKeys) {
    try {
      appendTrace({
        sessionId: identity.session_id,
        role: identity.role,
        agentName: identity.display_name || identity.role,
        runtime,
        actor_type: actorType,
        operation: toolName,
        filePath: key,
        purpose: identity.goal || '',
        result: toolName === 'Bash' ? extractResult(input) : null,
      });
    } catch (e) {
      // Non-fatal: log and continue
      process.stderr.write(`AIDS post-trace error: ${e.message}\n`);
    }
  }

  // Surface trace info to agent
  const mainKey = resourceKeys[0];
  process.stderr.write(
    `AIDS trace: ${toolName} ${mainKey} | ${actorType}/${runtime} ${identity.role}/${identity.session_id.slice(0, 8)}\n`
  );

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
 * Extract resource keys: file path for Write/Read/Edit,
 * bash:hash + parsed file paths for Bash.
 */
function extractResourceKeys(toolName, toolInput) {
  if (toolName === 'Bash') {
    return extractBashResources(toolInput.command || '');
  }
  const fp = toolInput.file_path || toolInput.path || '';
  return fp ? [fp] : [`tool:${toolName || 'unknown'}`];
}

/**
 * Parse Bash command for file-mutation targets.
 */
function extractBashResources(command) {
  if (!command) return [];
  const results = [];
  const hash = crypto.createHash('sha256').update(command).digest('hex').slice(0, 16);
  results.push(`bash:${hash}`);

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

/**
 * Extract a minimal result summary from the tool response.
 */
function extractResult(input) {
  const resp = input.tool_result || input.tool_response;
  if (!resp) return null;
  if (typeof resp === 'string') return { status: resp.length > 200 ? 'truncated' : 'ok', length: resp.length };
  if (typeof resp === 'object') return { status: resp.error ? 'error' : 'ok' };
  return null;
}
