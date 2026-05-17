/**
 * AIDS (Agent-ID System) — Trace Store
 *
 * TraceRecord schema:
 * { traceId, sessionId, role, runtime, actor_type, operation, filePath, purpose, timestamp, prevTraceId }
 *
 * Storage: ~/.aids/traces/YYYY-MM-DD.jsonl (append-only)
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { TRACES_DIR } = require('./constants');

function envFirst(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

function inferRuntime(entry) {
  return String(entry.runtime || envFirst('AIDS_RUNTIME', 'AID_RUNTIME', 'SELFTOOLS_RUNTIME', 'ZHUYI_RUNTIME') || 'unknown').toLowerCase();
}

function inferActorType(entry, runtime) {
  const actorType = entry.actor_type || entry.actorType || envFirst('AIDS_ACTOR_TYPE', 'AID_ACTOR_TYPE', 'SELFTOOLS_ACTOR_TYPE', 'ZHUYI_ACTOR_TYPE');
  if (actorType) return String(actorType).toLowerCase();
  if (runtime === 'claude' || runtime === 'codex') return 'agent';
  if (runtime === 'bash') return envFirst('AIDS_SESSION_ID', 'AID_SESSION_ID', 'SESSION_ID', 'SELFTOOLS_SESSION_ID', 'ZHUYI_SESSION_ID') ? 'human' : 'bash';
  return 'unknown';
}

function ensureDir() {
  if (!fs.existsSync(TRACES_DIR)) {
    fs.mkdirSync(TRACES_DIR, { recursive: true });
  }
}

function todayFile() {
  const d = new Date();
  const date = d.toISOString().slice(0, 10); // YYYY-MM-DD
  return path.join(TRACES_DIR, `${date}.jsonl`);
}

/**
 * Append a trace record.
 * @param {{ sessionId: string, role: string, operation: string, filePath?: string, purpose?: string, prevTraceId?: string }} entry
 * @returns {object} The full TraceRecord (with traceId, timestamp)
 */
function append(entry) {
  ensureDir();
  const traceId = `trace_${crypto.randomBytes(6).toString('hex')}`;
  const runtime = inferRuntime(entry);
  const actor_type = inferActorType(entry, runtime);
  const record = {
    traceId,
    sessionId: entry.sessionId || 'unknown',
    role: entry.role || 'unknown',
    runtime,
    actor_type,
    actorType: actor_type,
    operation: entry.operation,
    filePath: entry.filePath || '',
    purpose: entry.purpose || '',
    timestamp: Date.now(),
    prevTraceId: entry.prevTraceId || null,
  };

  const line = JSON.stringify(record) + '\n';
  fs.appendFileSync(todayFile(), line, 'utf-8');
  return record;
}

/**
 * Read traces for a given date.
 * @param {string} dateStr - YYYY-MM-DD format
 * @returns {object[]} Array of TraceRecord
 */
function readDate(dateStr) {
  const filePath = path.join(TRACES_DIR, `${dateStr}.jsonl`);
  if (!fs.existsSync(filePath)) return [];
  const lines = fs.readFileSync(filePath, 'utf-8').trim().split('\n').filter(Boolean);
  return lines.map((l) => JSON.parse(l));
}

/**
 * Read today's traces.
 * @returns {object[]}
 */
function readToday() {
  const d = new Date();
  return readDate(d.toISOString().slice(0, 10));
}

/**
 * Find recent traces for a specific file path.
 * @param {string} filePath
 * @param {number} limit
 * @returns {object[]}
 */
function findByPath(filePath, limit = 5) {
  const traces = readToday();
  return traces
    .filter((t) => t.filePath === filePath)
    .slice(-limit);
}

module.exports = { append, readDate, readToday, findByPath };
