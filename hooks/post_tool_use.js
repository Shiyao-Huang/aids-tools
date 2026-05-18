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
 */

const { resolve } = require('../lib/session');
const { appendTrace, TRACE_OPERATIONS } = require('../src/trace/trace');
const {
  inferRuntime, inferActorType, resolveAgentId,
  extractResourceKeys,
} = require('./_aid_shared');

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
  const agentId = resolveAgentId(identity);

  // Extract resource keys (may be multiple for Bash with file mutations)
  const resourceKeys = extractResourceKeys(toolName, toolInput);
  // Post hook: always produce at least a tool: key for tracing
  const traceKeys = resourceKeys.length > 0
    ? resourceKeys
    : [`tool:${toolName || 'unknown'}`];

  // Record a trace for each resource key
  for (const key of traceKeys) {
    try {
      appendTrace({
        sessionId: identity.session_id,
        role: identity.role,
        agent_id: agentId,
        agentName: identity.display_name || identity.role,
        runtime,
        actor_type: actorType,
        operation: toolName,
        filePath: key,
        purpose: identity.goal || '',
        result: extractResult(input),
      });
    } catch (e) {
      // Non-fatal: log and continue
      process.stderr.write(`AIDS post-trace error: ${e.message}\n`);
    }
  }

  // Surface trace info to agent
  const mainKey = traceKeys[0];
  process.stderr.write(
    `AIDS trace: ${toolName} ${mainKey} | ${actorType}/${runtime} ${identity.role}/${identity.session_id.slice(0, 8)} | agent_id=${agentId}\n`
  );

  process.exit(0);
}

/**
 * Extract a result summary from the tool response.
 */
function extractResult(input) {
  const resp = input.tool_result || input.tool_response;
  if (resp === undefined || resp === null) return null;

  if (typeof resp === 'string') {
    const isError = input.is_error === true || input.isError === true;
    const exitCode = parseExitCode(resp);
    return {
      status: isError ? 'error' : 'ok',
      is_error: isError,
      exit_code: exitCode,
      length: resp.length,
    };
  }

  if (typeof resp === 'object') {
    const isError = resp.error || resp.is_error || input.is_error === true || input.isError === true;
    const exitCode = resp.exit_code ?? resp.exitCode ?? parseExitCode(resp.stderr || resp.stdout || '');
    return {
      status: isError ? 'error' : 'ok',
      is_error: !!isError,
      exit_code: exitCode,
    };
  }

  return null;
}

function parseExitCode(text) {
  if (typeof text !== 'string' || !text) return null;
  const m = text.match(/[Ee]xit\s+code:\s*(\d+)/);
  if (m) return parseInt(m[1], 10);
  return null;
}
