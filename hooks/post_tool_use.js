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
        result: extractResult(input),
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
 * Parse Bash command for file-mutation targets and read-only file targets.
 */
function extractBashResources(command) {
  if (!command) return [];
  const path = require('path');
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

/**
 * Extract a result summary from the tool response.
 * Captures status (ok/error), exit_code, and is_error for all tools.
 */
function extractResult(input) {
  const resp = input.tool_result || input.tool_response;
  if (resp === undefined || resp === null) return null;

  // String result (common for Bash output, tool responses)
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

  // Object result
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

/**
 * Try to extract exit code from Bash output text.
 * Common patterns: "Exit code: N" or "[error] exit code N" at the end of output.
 */
function parseExitCode(text) {
  if (typeof text !== 'string' || !text) return null;
  const m = text.match(/[Ee]xit\s+code:\s*(\d+)/);
  if (m) return parseInt(m[1], 10);
  return null;
}
