#!/usr/bin/env node
/**
 * AIDS (Agent-ID System) — Codex Shim
 *
 * Wraps Codex CLI tool calls with identity injection + trace recording.
 * Uses the full-featured src/trace/trace.js for timeline events + index.
 *
 * Usage:
 *   codex-shim.js <original-codex-args...>
 *
 * Environment (primary AIDS_*, legacy aliases accepted):
 *   AIDS_SESSION_ID — primary session identity
 *   AIDS_ROLE       — primary agent role
 *   AIDS_INTENT     — current task/goal
 *   AIDS_TASK_ID    — task being worked on
 */

const { spawn } = require('child_process');
const path = require('path');
const { resolve } = require('../lib/session');
const { appendTrace } = require('../src/trace/trace');

const identity = resolve();
const runtime = 'codex';
const actorType = 'agent';

// Register/heartbeat in session store
try {
  const { register } = require('../lib/session');
  register({ session_id: identity.session_id, runtime, display_name: 'Codex Agent' });
} catch { /* non-fatal */ }

const realCodex = findRealCodex();
const args = process.argv.slice(2);

const child = spawn(realCodex, args, {
  stdio: 'inherit',
  env: {
    ...process.env,
    AIDS_SESSION_ID: identity.session_id,
    AIDS_ROLE: identity.role,
    AIDS_INTENT: identity.goal,
    AIDS_RUNTIME: runtime,
    AIDS_ACTOR_TYPE: actorType,
    // Legacy aliases for backward compat
    ZHUYI_SESSION_ID: process.env.ZHUYI_SESSION_ID || identity.session_id,
    ZHUYI_ROLE: process.env.ZHUYI_ROLE || identity.role,
    ZHUYI_INTENT: process.env.ZHUYI_INTENT || identity.goal,
  },
});

child.on('exit', (code) => {
  const targetArg = args.find((a) => !a.startsWith('-')) || '';
  try {
    appendTrace({
      sessionId: identity.session_id,
      role: identity.role,
      agentName: 'Codex Agent',
      runtime,
      actor_type: actorType,
      operation: 'codex-invocation',
      filePath: targetArg || `codex:${args.join(' ').slice(0, 60)}`,
      purpose: identity.goal || '',
      result: { status: code === 0 ? 'ok' : 'error', exitCode: code },
    });
  } catch { /* non-fatal */ }

  process.exit(code || 0);
});

function findRealCodex() {
  const shimDir = path.resolve(__dirname, '..', 'bin');
  const pathEntries = (process.env.PATH || '').split(path.delimiter);
  const cleanPath = pathEntries.filter((p) => p !== shimDir).join(path.delimiter);

  for (const bin of ['codex', 'openai-codex']) {
    try {
      const { execSync } = require('child_process');
      const result = execSync(`which ${bin}`, {
        env: { ...process.env, PATH: cleanPath },
        encoding: 'utf-8',
      }).trim();
      if (result) return result;
    } catch { /* try next */ }
  }

  return 'codex';
}
