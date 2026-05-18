/**
 * AIDS (Agent-ID System) — Session Registry (Node.js library)
 *
 * SessionRecord per data-model.md:
 * { session_id, role, display_name, team_id, task_id, goal,
 *   project_path, runtime, model, started_at, last_seen_at, status }
 *
 * Storage: ~/.aids/sessions/{session_id}.json
 *
 * NOTE: The primary public CLI is `aids` (implemented by bin/selftools for
 * compatibility). This module provides a Node.js API for JS-based hooks/tools.
 * Field names use snake_case to match data-model.md exactly.
 */

const fs = require('fs');
const path = require('path');
const { SESSIONS_DIR } = require('./constants');

const VALID_STATUSES = ['active', 'retired', 'archived'];

function ensureDir() {
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}

function sessionPath(sessionId) {
  return path.join(SESSIONS_DIR, `${sessionId}.json`);
}

// ── CRUD ───────────────────────────────────────────────────────────────

/**
 * register — Create or update a SessionRecord.
 *
 * If the session already exists, merges new fields and bumps last_seen_at.
 * started_at is preserved from the original record.
 *
 * @param {object} params - SessionRecord fields (session_id required)
 * @returns {object} The persisted SessionRecord
 */
function register(params) {
  if (!params.session_id) throw new Error('session_id is required');

  ensureDir();
  const filePath = sessionPath(params.session_id);
  const now = Date.now();
  let existing = null;

  try {
    existing = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    existing = null;
  }

  if (existing) {
    // Merge: new fields win, but keep started_at from original
    const merged = { ...existing, ...params, started_at: existing.started_at, last_seen_at: now };
    fs.writeFileSync(filePath, JSON.stringify(merged, null, 2) + '\n', 'utf-8');
    return merged;
  }

  // Fresh session
  const record = {
    session_id: params.session_id,
    role: params.role || 'unknown',
    display_name: params.display_name || '',
    team_id: params.team_id || '',
    task_id: params.task_id || null,
    goal: params.goal || '',
    project_path: params.project_path || '',
    runtime: params.runtime || 'claude',
    model: params.model || '',
    started_at: params.started_at || now,
    last_seen_at: now,
    status: 'active',
  };
  fs.writeFileSync(filePath, JSON.stringify(record, null, 2) + '\n', 'utf-8');
  return record;
}

/**
 * lookup — Look up a session by ID.
 * @param {string} sessionId
 * @returns {object|null} SessionRecord or null if not found
 */
function lookup(sessionId) {
  const filePath = sessionPath(sessionId);
  if (!fs.existsSync(filePath)) return null;
  try { return JSON.parse(fs.readFileSync(filePath, 'utf-8')); } catch { return null; }
}

function envFirst(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

/** Return val if non-empty and not a sentinel ('unknown', 'unspecified'), else null — lets env vars override stale records. */
function known(val) {
  return (val && val !== 'unknown' && val !== 'unspecified') ? val : null;
}

/**
 * resolve — Resolve session identity from env vars or explicit ID.
 * Returns a minimal identity object even if no session file exists.
 * @param {string?} explicitId
 * @returns {{ session_id, role, goal, task_id }}
 */
function resolve(explicitId) {
  const sessionId = explicitId || envFirst('AIDS_SESSION_ID', 'AID_SESSION_ID', 'SESSION_ID', 'SELFTOOLS_SESSION_ID', 'ZHUYI_SESSION_ID', 'AHA_SESSION_ID') || 'unknown';
  const record = lookup(sessionId);
  return {
    session_id: sessionId,
    role: known(record && record.role) || envFirst('AIDS_ROLE', 'AID_ROLE', 'AHA_AGENT_ROLE', 'ROLE', 'SELFTOOLS_ROLE', 'ZHUYI_ROLE', 'AHA_ROLE') || 'unknown',
    goal: known(record && record.goal) || envFirst('AIDS_INTENT', 'AID_INTENT', 'AHA_INTENT', 'AHA_AGENT_SCOPE_SUMMARY', 'INTENT', 'SELFTOOLS_INTENT', 'ZHUYI_INTENT', 'AHA_TASK_TITLE') || '',
    task_id: known(record && record.task_id) || envFirst('AIDS_TASK_ID', 'AID_TASK_ID', 'TASK_ID', 'SELFTOOLS_TASK_ID', 'ZHUYI_TASK_ID', 'AHA_TASK_ID') || '',
    team_id: known(record && record.team_id) || envFirst('AIDS_TEAM_ID', 'AHA_ROOM_ID') || '',
    display_name: known(record && record.display_name) || envFirst('AIDS_SESSION_NAME', 'AHA_SESSION_NAME') || '',
    runtime: known(record && record.runtime) || envFirst('AIDS_RUNTIME', 'AID_RUNTIME', 'SELFTOOLS_RUNTIME', 'ZHUYI_RUNTIME') || 'unknown',
    actor_type: known(record && record.actor_type) || envFirst('AIDS_ACTOR_TYPE', 'AID_ACTOR_TYPE', 'SELFTOOLS_ACTOR_TYPE', 'ZHUYI_ACTOR_TYPE') || 'unknown',
  };
}

/**
 * heartbeat — Bump last_seen_at for a session.
 * @param {string} sessionId
 * @returns {object|null} Updated record, or null if not found
 */
function heartbeat(sessionId) {
  const filePath = sessionPath(sessionId);
  const record = lookup(sessionId);
  if (!record) return null;
  record.last_seen_at = Date.now();
  fs.writeFileSync(filePath, JSON.stringify(record, null, 2) + '\n', 'utf-8');
  return record;
}

/**
 * retire — Mark a session as retired.
 * @param {string} sessionId
 * @param {string} [reason] - Optional retirement reason
 * @returns {object|null} Updated record, or null if not found
 */
function retire(sessionId, reason) {
  const record = lookup(sessionId);
  if (!record) return null;
  record.status = 'retired';
  record.last_seen_at = Date.now();
  if (reason) record.retire_reason = reason;
  fs.writeFileSync(sessionPath(sessionId), JSON.stringify(record, null, 2) + '\n', 'utf-8');
  return record;
}

/**
 * updateGoal — Change the task_id and/or goal for a session.
 * @param {string} sessionId
 * @param {{ task_id?: string, goal?: string }} updates
 * @returns {object|null} Updated record
 */
function updateGoal(sessionId, updates) {
  const record = lookup(sessionId);
  if (!record) return null;
  if (updates.task_id !== undefined) record.task_id = updates.task_id;
  if (updates.goal !== undefined) record.goal = updates.goal;
  record.last_seen_at = Date.now();
  fs.writeFileSync(sessionPath(sessionId), JSON.stringify(record, null, 2) + '\n', 'utf-8');
  return record;
}

/**
 * listActive — Return all sessions with status='active'.
 * @param {{ role?: string, team_id?: string, runtime?: string }} [filter]
 * @returns {object[]}
 */
function listActive(filter = {}) {
  ensureDir();
  let records = fs.readdirSync(SESSIONS_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => { try { return JSON.parse(fs.readFileSync(path.join(SESSIONS_DIR, f), 'utf-8')); } catch { return null; } })
    .filter(Boolean);

  records = records.filter(r => r.status === 'active');
  if (filter.role) records = records.filter(r => r.role === filter.role);
  if (filter.team_id) records = records.filter(r => r.team_id === filter.team_id);
  if (filter.runtime) records = records.filter(r => r.runtime === filter.runtime);
  return records;
}

/**
 * listAll — Return all sessions regardless of status.
 * @returns {object[]}
 */
function listAll() {
  ensureDir();
  return fs.readdirSync(SESSIONS_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => { try { return JSON.parse(fs.readFileSync(path.join(SESSIONS_DIR, f), 'utf-8')); } catch { return null; } })
    .filter(Boolean);
}

/**
 * whois — Human-readable summary of a session.
 * @param {string} sessionId
 * @returns {string}
 */
function whois(sessionId) {
  const r = lookup(sessionId);
  if (!r) return `unknown session: ${sessionId}`;
  const ageMin = Math.round((Date.now() - (r.started_at || 0)) / 60000);
  const ago = r.last_seen_at ? Math.round((Date.now() - r.last_seen_at) / 60000) : '?';
  return [
    `Session: ${r.session_id}`,
    `  Role:         ${r.role}`,
    `  Name:         ${r.display_name || '(unnamed)'}`,
    `  Runtime:      ${r.runtime}${r.model ? ' / ' + r.model : ''}`,
    `  Goal:         ${r.goal || '(none)'}`,
    `  Task:         ${r.task_id || '(none)'}`,
    `  Team:         ${r.team_id || '(none)'}`,
    `  Project:      ${r.project_path || '(none)'}`,
    `  Status:       ${r.status}`,
    `  Uptime:       ${ageMin}m`,
    `  Last seen:    ${ago}m ago`,
  ].join('\n');
}

module.exports = { register, lookup, resolve, heartbeat, retire, updateGoal, listActive, listAll, whois };
