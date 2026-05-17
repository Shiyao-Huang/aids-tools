#!/usr/bin/env node
/**
 * AIDS (Agent-ID System) — Codex Shim
 *
 * Wraps Codex CLI tool calls with identity injection + trace recording.
 * Installed as a PATH wrapper that intercepts codex invocations.
 *
 * Usage:
 *   codex-shim.js <original-codex-args...>
 *
 * Environment:
 *   AIDS_SESSION_ID — primary session identity
 *   AIDS_ROLE       — primary agent role
 *   AIDS_INTENT     — current task/goal
 *   AIDS_TASK_ID    — task being worked on
 *   ZHUYI_*         — legacy aliases accepted during migration
 */

const { spawn } = require('child_process');
const path = require('path');
const { resolve } = require('../lib/session');
const { append } = require('../lib/trace');
const { update } = require('../lib/index');

// Resolve this session's identity
const identity = resolve();

// Register/heartbeat in session store
try {
  const { register } = require('../lib/session');
  register({ session_id: identity.session_id, runtime: 'codex', actor_type: 'agent' });
} catch { /* non-fatal */ }

// Find the real codex binary
const realCodex = findRealCodex();

// Forward all args to real codex
const args = process.argv.slice(2);
const child = spawn(realCodex, args, {
  stdio: 'inherit',
  env: {
    ...process.env,
    AIDS_SESSION_ID: identity.session_id,
    AIDS_ROLE: identity.role,
    AIDS_INTENT: identity.goal,
    ZHUYI_SESSION_ID: process.env.ZHUYI_SESSION_ID || identity.session_id,
    ZHUYI_ROLE: process.env.ZHUYI_ROLE || identity.role,
    ZHUYI_INTENT: process.env.ZHUYI_INTENT || identity.goal,
  },
});

child.on('exit', (code) => {
  // Record a trace for the codex invocation
  try {
    const record = append({
      sessionId: identity.session_id,
      role: identity.role,
      runtime: 'codex',
      actor_type: 'agent',
      operation: 'codex-invocation',
      filePath: args.find((a) => !a.startsWith('-')) || '',
      purpose: identity.goal || '',
    });
    if (record.filePath) {
      update(record.filePath, record.traceId);
    }
  } catch { /* non-fatal */ }

  process.exit(code || 0);
});

function findRealCodex() {
  // Remove our shim directory from PATH to find the real binary
  const shimDir = path.resolve(__dirname, '..', 'bin');
  const pathEntries = (process.env.PATH || '').split(path.delimiter);
  const cleanPath = pathEntries.filter((p) => p !== shimDir).join(path.delimiter);

  // Common codex binary names
  const binaries = ['codex', 'openai-codex'];
  for (const bin of binaries) {
    try {
      const { execSync } = require('child_process');
      const result = execSync(`which ${bin}`, {
        env: { ...process.env, PATH: cleanPath },
        encoding: 'utf-8',
      }).trim();
      if (result) return result;
    } catch { /* try next */ }
  }

  // Fallback — assume codex is somewhere on PATH
  return 'codex';
}
