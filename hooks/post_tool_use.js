#!/usr/bin/env node
/**
 * AIDS (Agent-ID System) — PostToolUse Hook
 *
 * Runs AFTER any tool call in Claude Code.
 * Records a TraceRecord with actor_type, runtime, resource_key.
 * Updates the Resource Index for fast lookup.
 *
 * Claude Code hook protocol:
 *   - Receives JSON on stdin: { tool_name, tool_input, tool_result }
 *   - stderr output is shown to the agent
 *   - exit 0 = pass through
 */

const crypto = require('crypto');
const { resolve } = require('../lib/session');
const { append } = require('../lib/trace');
const { update } = require('../lib/index');
const { TRACED_TOOLS } = require('../lib/constants');

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

  // Only trace the tools we care about
  if (!TRACED_TOOLS.has(toolName)) {
    process.exit(0);
  }

  // Extract resource key: file path or bash:{hash}
  const resourceKey = extractResourceKey(toolName, toolInput);
  if (!resourceKey) {
    process.exit(0);
  }

  // Resolve identity (includes runtime + actor_type from session/env)
  const identity = resolve();

  // Append trace record with runtime + actor_type
  const record = append({
    sessionId: identity.session_id,
    role: identity.role,
    runtime: identity.runtime || 'claude',
    actor_type: identity.actor_type || 'agent',
    operation: toolName,
    filePath: resourceKey,
    purpose: identity.goal || '',
  });

  // Update resource index for fast lookup
  update(resourceKey, record.traceId);

  // Surface the trace ID to the agent (lightweight — one line to stderr)
  const actorLabel = record.actor_type || 'agent';
  const runtimeLabel = record.runtime || 'unknown';
  process.stderr.write(
    `AIDS trace: ${record.traceId} | ${toolName} ${resourceKey} | ${actorLabel}/${runtimeLabel} ${identity.role}/${identity.session_id.slice(0, 8)}\n`
  );

  process.exit(0);
}

/**
 * Extract a stable resource key from tool input.
 * File tools → file path. Bash → bash:{sha256(command)[:16]}.
 */
function extractResourceKey(toolName, toolInput) {
  if (toolName === 'Bash') {
    const cmd = toolInput.command || '';
    if (!cmd) return null;
    const hash = crypto.createHash('sha256').update(cmd).digest('hex').slice(0, 16);
    return `bash:${hash}`;
  }
  return toolInput.file_path || toolInput.path || '';
}
