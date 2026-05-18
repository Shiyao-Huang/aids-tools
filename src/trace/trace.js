#!/usr/bin/env node
'use strict';

/**
 * AIDS / Agent-ID System — Trace Chain Storage
 *
 * Zero-dependency, file-system backed operation ledger.
 * Canonical task storage:
 *   ~/.aids/traces/YYYY-MM-DD.ndjson
 *
 * Compatibility env vars are intentionally broad because the rest of the
 * project may still use earlier AID/selftools/ZHUYI naming in installed hooks.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const TRACE_OPERATIONS = new Set([
  'Write',
  'Read',
  'Edit',
  'MultiEdit',
  'NotebookEdit',
  'apply_patch',
  'ApplyPatch',
  'Bash',
  'Shell',
  'exec_command',
  'WebFetch',
  'WebSearch',
  'Grep',
  'Glob',
  'LS',
  'TodoWrite',
  'update_plan',
  'Task',
  'spawn_agent',
  'send_input',
  'wait_agent',
  'mcp',
]);
const WRITE_OPERATIONS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'apply_patch', 'ApplyPatch']);
const LOCK_RETRY_MS = 25;
const LOCK_TIMEOUT_MS = 2500;
const DEFAULT_TRACE_SCAN_DAYS = 30;

function getStoreHome() {
  return path.resolve(
    expandHome(
      process.env.AIDS_HOME ||
        process.env.AIDS_DATA_DIR ||
        process.env.AID_HOME ||
        process.env.AID_DATA_DIR ||
        process.env.CONSCIOUS_TOOLS_HOME ||
        process.env.SELFTOOLS_DATA_DIR ||
        process.env.ZHUYI_DATA_DIR ||
        process.env.ZHUYI_HOME ||
        path.join(os.homedir(), '.aids'),
    ),
  );
}

function expandHome(value) {
  if (!value || value === '~') return os.homedir();
  if (value.startsWith('~/')) return path.join(os.homedir(), value.slice(2));
  return value;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
  return dirPath;
}

function tracesDir() {
  return ensureDir(path.join(getStoreHome(), 'traces'));
}

function indexDir() {
  return ensureDir(path.join(getStoreHome(), 'index'));
}

function locksDir() {
  return ensureDir(path.join(getStoreHome(), 'locks'));
}

function datePart(timestamp = new Date()) {
  const d = timestamp instanceof Date ? timestamp : new Date(timestamp);
  return Number.isNaN(d.getTime()) ? new Date().toISOString().slice(0, 10) : d.toISOString().slice(0, 10);
}

function traceFileForDate(date = datePart()) {
  return path.join(tracesDir(), `${date}.ndjson`);
}

function legacyTraceFileForDate(date = datePart()) {
  return path.join(tracesDir(), `${date}.jsonl`);
}

function timelineDir() {
  return ensureDir(path.join(getStoreHome(), 'timeline'));
}

function timelineFileForDate(date = datePart()) {
  return path.join(timelineDir(), `${date}.jsonl`);
}

function appendTimelineEvent(type, record) {
  const timestampIso = toIsoTimestamp(record.timestamp || record.timestamp_iso || new Date());
  const timestampMs = new Date(timestampIso).getTime();
  const event = {
    event_id: newUuid(),
    event_type: type,
    schema_version: 'aids.timeline.v1',
    timestamp: Number.isFinite(timestampMs) ? timestampMs : Date.now(),
    timestamp_iso: timestampIso,
    runtime: record.runtime || 'unknown',
    actor_type: record.actor_type || record.actorType || 'unknown',
    trace_id: record.traceId || record.trace_id || null,
    rating_id: record.ratingId || record.rating_id || null,
    session_id: record.sessionId || record.session_id || record.ratedBy || record.rater_session_id || null,
    resource_path: record.filePath || record.resource_path || null,
    payload: record,
  };
  appendLineAtomic(timelineFileForDate(datePart(timestampIso)), event);
  return event;
}

function newUuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return [4, 2, 2, 2, 6]
    .map((n) => crypto.randomBytes(n).toString('hex'))
    .join('-');
}

function sleep(ms) {
  const delay = Math.max(0, Number(ms) || 0);
  if (!delay) return;

  // Keep the lock API synchronous without relying on Atomics.wait /
  // SharedArrayBuffer support in worker-like runtimes.
  const result = spawnSync(
    process.execPath,
    ['-e', 'setTimeout(() => {}, Number(process.argv[1]) || 0);', String(delay)],
    { stdio: 'ignore' },
  );

  if (result.error) {
    const deadline = Date.now() + delay;
    while (Date.now() < deadline) {
      // Fallback for environments where spawning node is unavailable.
    }
  }
}

function withLock(name, fn) {
  ensureDir(locksDir());
  const safe = String(name).replace(/[^A-Za-z0-9_.-]/g, '_');
  const lockPath = path.join(locksDir(), `${safe}.lockdir`);
  const start = Date.now();
  while (true) {
    try {
      fs.mkdirSync(lockPath);
      break;
    } catch (error) {
      if (error && error.code === 'EEXIST' && Date.now() - start < LOCK_TIMEOUT_MS) {
        sleep(LOCK_RETRY_MS);
        continue;
      }
      throw error;
    }
  }
  try {
    return fn();
  } finally {
    try {
      fs.rmSync(lockPath, { recursive: true, force: true });
    } catch (_) {
      // Best-effort cleanup; lock timeout protects future callers.
    }
  }
}

function appendLineAtomic(filePath, record) {
  ensureDir(path.dirname(filePath));
  const lockName = `append-${path.basename(filePath)}`;
  return withLock(lockName, () => {
    const line = `${JSON.stringify(record)}\n`;
    fs.appendFileSync(filePath, line, 'utf8');
    return record;
  });
}

function readNdjsonFile(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const text = fs.readFileSync(filePath, 'utf8');
  if (!text.trim()) return [];
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return normalizeTrace(JSON.parse(line));
      } catch (_) {
        return null;
      }
    })
    .filter(Boolean);
}

function allTraceFiles() {
  const dir = tracesDir();
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((name) => name.endsWith('.ndjson') || name.endsWith('.jsonl'))
    .sort()
    .map((name) => path.join(dir, name));
}

function parseTraceScanDays(value, fallback = DEFAULT_TRACE_SCAN_DAYS) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'string' && value.trim().toLowerCase() === 'all') return Infinity;
  const days = Number(value);
  if (!Number.isInteger(days) || days < 0) {
    throw new Error(`days must be a non-negative integer or "all"; got ${value}`);
  }
  return days === 0 ? Infinity : days;
}

function traceFileDate(filePath) {
  const match = path.basename(filePath).match(/^(\d{4})-(\d{2})-(\d{2})\.(?:ndjson|jsonl)$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    return null;
  }
  return date;
}

function traceScanStartDate(days, now = new Date()) {
  if (!Number.isFinite(days)) return null;
  const date = now instanceof Date ? now : new Date(now);
  if (Number.isNaN(date.getTime())) throw new Error(`invalid scan reference date: ${now}`);
  const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return start;
}

function filterTraceFilesByDays(files, days, now = new Date()) {
  if (!Number.isFinite(days)) return files;
  const startDate = traceScanStartDate(days, now);
  return files.filter((filePath) => {
    const fileDate = traceFileDate(filePath);
    return fileDate && fileDate >= startDate;
  });
}

function readAllTraces(options = {}) {
  const scanOptions = options && typeof options === 'object' ? options : { days: options };
  const days = parseTraceScanDays(scanOptions.days);
  const files = filterTraceFilesByDays(allTraceFiles(), days, scanOptions.now);
  return files.flatMap(readNdjsonFile).sort(compareTraceTime);
}

function compareTraceTime(a, b) {
  return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
}

function normalizeFilePath(filePath, cwd = process.cwd()) {
  if (!filePath) return '';
  const raw = String(filePath);
  if (raw.startsWith('bash:') || /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(raw)) return raw;
  const expanded = expandHome(raw);
  const absolute = path.isAbsolute(expanded) ? expanded : path.join(cwd || process.cwd(), expanded);
  return path.resolve(absolute);
}

function base64Url(value) {
  return Buffer.from(value, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function indexPathForFile(filePath) {
  return path.join(indexDir(), `${base64Url(filePath)}.json`);
}

function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return fallback;
  }
}

function writeJsonAtomic(filePath, data) {
  ensureDir(path.dirname(filePath));
  const tmp = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, filePath);
}

function readIndex(filePath) {
  const normalizedPath = normalizeFilePath(filePath);
  return readJson(indexPathForFile(normalizedPath), null);
}

function updateIndex(record) {
  if (!record.filePath) return;
  const idxPath = indexPathForFile(record.filePath);
  withLock(`index-${base64Url(record.filePath)}`, () => {
    const index = readJson(idxPath, null) || {
      filePath: record.filePath,
      traceIds: [],
      traces: [],
      count: 0,
    };
    index.filePath = record.filePath;
    index.traceIds = Array.isArray(index.traceIds) ? index.traceIds : [];
    index.traces = Array.isArray(index.traces) ? index.traces : [];
    index.traceIds.push(record.traceId);
    index.traceIds = index.traceIds.slice(-1000);
    index.traces.push({
      traceId: record.traceId,
      sessionId: record.sessionId,
      agentName: record.agentName,
      role: record.role,
      actor_type: record.actor_type,
      runtime: record.runtime,
      operation: record.operation,
      purpose: record.purpose,
      timestamp: record.timestamp,
    });
    index.traces = index.traces.slice(-1000);
    index.lastTraceId = record.traceId;
    index.lastActor = record.sessionId;
    index.lastActorName = record.agentName;
    index.lastIntent = record.purpose;
    index.lastRuntime = record.runtime;
    index.lastActorType = record.actor_type;
    index.lastTouchedAt = record.timestamp;
    if (WRITE_OPERATIONS.has(record.operation)) {
      index.lastWriter = record.sessionId;
      index.lastWriterName = record.agentName;
      index.lastWriteIntent = record.purpose;
      index.lastWriteAt = record.timestamp;
    }
    index.count = Number(index.count || 0) + 1;
    writeJsonAtomic(idxPath, index);
  });
}

function canonicalOperation(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const found = Array.from(TRACE_OPERATIONS).find((op) => op.toLowerCase() === raw.toLowerCase());
  return found || raw;
}

function envFirst(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

function isToolEnvelope(input) {
  return input && typeof input === 'object' && input.schema_version && input.tool && input.session && input.resource;
}

function envelopeToTraceInput(input) {
  const resource = input.resource || {};
  const session = input.session || {};
  const intent = input.intent || {};
  const tool = input.tool || {};
  const metadata = Object.assign({}, input.metadata || {}, { tool_envelope: input });
  return {
    traceId: input.trace_id,
    prevTraceId: input.parent_trace_id || input.parentTraceId,
    sessionId: session.id,
    agentName: session.display_name || session.id,
    role: session.role,
    actor_type: session.actor_type,
    runtime: input.runtime || session.runtime,
    operation: tool.name,
    filePath: resource.key || resource.path,
    purpose: intent.value,
    timestamp: input.timestamps && (input.timestamps.finished_at || input.timestamps.received_at),
    metadata,
    result: tool.response || input.result || null,
    cwd: resource.cwd || session.project_path,
  };
}

function inferRuntime(input, operation, filePath) {
  const runtime =
    input.runtime ||
    input.host_runtime ||
    (input.metadata && input.metadata.runtime) ||
    envFirst('AIDS_RUNTIME', 'AID_RUNTIME', 'SELFTOOLS_RUNTIME', 'ZHUYI_RUNTIME', 'RUNTIME');
  if (runtime) return String(runtime).toLowerCase();
  if (operation === 'Bash' || String(filePath || '').startsWith('bash:')) return 'bash';
  return 'unknown';
}

function inferActorType(input, runtime) {
  const actorType =
    input.actor_type ||
    input.actorType ||
    (input.metadata && (input.metadata.actor_type || input.metadata.actorType)) ||
    envFirst('AIDS_ACTOR_TYPE', 'AID_ACTOR_TYPE', 'SELFTOOLS_ACTOR_TYPE', 'ZHUYI_ACTOR_TYPE', 'ACTOR_TYPE');
  if (actorType) return String(actorType).toLowerCase();
  if (runtime === 'bash') return process.env.AIDS_SESSION_ID || process.env.AID_SESSION_ID ? 'human' : 'bash';
  if (runtime === 'claude' || runtime === 'codex') return 'agent';
  return 'unknown';
}

function normalizeTrace(input = {}) {
  const source = isToolEnvelope(input) ? envelopeToTraceInput(input) : input;
  const operation = canonicalOperation(source.operation || source.tool || source.toolName);
  const cwd = source.cwd || (source.metadata && source.metadata.cwd) || process.cwd();
  const filePath = normalizeFilePath(source.filePath || source.targetPath || source.target_path || source.resource_path || source.resourcePath || '', cwd);
  const purpose = (source.purpose && source.purpose !== 'unspecified' ? source.purpose : null) || (source.intent && source.intent !== 'unspecified' ? source.intent : null) || envFirst('AIDS_INTENT', 'AHA_SESSION_NAME', 'AHA_TASK_TITLE') || '';
  const sessionId =
    source.sessionId ||
    source.session_id ||
    envFirst('AIDS_SESSION_ID', 'AID_SESSION_ID', 'SESSION_ID', 'SELFTOOLS_SESSION_ID', 'ZHUYI_SESSION_ID') ||
    'unknown';
  const prevTraceId = source.prevTraceId || source.parentTraceId || source.parent_trace_id || source.parentOpId || source.parent_op_id || source.prev_trace_id || null;
  const timestamp = toIsoTimestamp(source.timestamp || source.timestamp_iso || source.createdAt || new Date());
  const metadata = Object.assign({}, source.metadata || {}, source.metadata_json ? safeJson(source.metadata_json) : {});
  const runtime = inferRuntime(source, operation, filePath);
  const actor_type = inferActorType(source, runtime);
  const record = Object.assign({}, source, {
    traceId: source.traceId || source.trace_id || newUuid(),
    prevTraceId,
    parentTraceId: prevTraceId,
    sessionId,
    agentName:
      source.agentName ||
      source.agent_name ||
      source.displayName ||
      source.display_name ||
      envFirst('AIDS_AGENT_NAME', 'AID_AGENT_NAME', 'AGENT_NAME', 'SELFTOOLS_DISPLAY_NAME', 'ZHUYI_DISPLAY_NAME', 'AIDS_ROLE', 'AID_ROLE', 'ROLE', 'SELFTOOLS_ROLE', 'ZHUYI_ROLE') ||
      'unknown',
    role: (source.role && source.role !== 'unknown' && source.role !== 'unspecified' ? source.role : null) || envFirst('AIDS_ROLE', 'AID_ROLE', 'ROLE', 'SELFTOOLS_ROLE', 'ZHUYI_ROLE', 'AHA_AGENT_ROLE', 'AHA_ROLE') || 'unknown',
    actor_type,
    actorType: actor_type,
    runtime,
    operation,
    filePath,
    purpose,
    result: source.result || null,
    timestamp,
    metadata,
  });

  // Compatibility aliases for docs/bin/selftools and earlier task wording.
  record.trace_id = record.traceId;
  record.prev_trace_id = record.prevTraceId;
  record.parent_trace_id = record.prevTraceId;
  record.session_id = record.sessionId;
  record.tool = record.operation;
  record.targetPath = record.filePath;
  record.target_path = record.filePath;
  record.resource_path = record.filePath;
  record.intent = record.purpose;
  record.parentOpId = record.prevTraceId;
  record.parent_op_id = record.prevTraceId;
  record.team_id = source.team_id || source.teamId || envFirst('AIDS_TEAM_ID', 'AHA_ROOM_ID') || null;
  record.timeline_path = timelineFileForDate(datePart(record.timestamp));
  return record;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch (_) {
    return {};
  }
}

function toIsoTimestamp(value) {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'number') return new Date(value).toISOString();
  if (typeof value === 'string') {
    const asNumber = Number(value);
    if (Number.isFinite(asNumber) && value.trim() !== '') return new Date(asNumber).toISOString();
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return date.toISOString();
  }
  return new Date().toISOString();
}

function validateTrace(record) {
  if (!TRACE_OPERATIONS.has(record.operation)) {
    throw new Error(`operation must be one of ${Array.from(TRACE_OPERATIONS).join('|')}; got ${record.operation || '<empty>'}`);
  }
  if (!record.filePath) throw new Error('filePath is required');
  if (!record.sessionId) throw new Error('sessionId is required');
}

function appendTrace(record) {
  const normalized = normalizeTrace(record);
  validateTrace(normalized);
  if (!normalized.prevTraceId) {
    const index = readIndex(normalized.filePath);
    normalized.prevTraceId = index && index.lastTraceId ? index.lastTraceId : null;
    normalized.prev_trace_id = normalized.prevTraceId;
    normalized.parentOpId = normalized.prevTraceId;
    normalized.parent_op_id = normalized.prevTraceId;
  }
  const file = traceFileForDate(datePart(normalized.timestamp));
  appendLineAtomic(file, normalized);
  appendTimelineEvent('trace', normalized);
  updateIndex(normalized);
  return normalized;
}

function getTraceById(traceId, options = {}) {
  if (!traceId) return null;
  const scanOpts = { days: 'all', ...options };
  return readAllTraces(scanOpts).find((trace) => trace.traceId === traceId || trace.trace_id === traceId) || null;
}

function getTracesForFile(filePath, limit = Infinity, options = {}) {
  const normalizedPath = normalizeFilePath(filePath);
  const index = readIndex(normalizedPath);
  let traces;
  if (index && Array.isArray(index.traceIds) && index.traceIds.length) {
    const ids = new Set(index.traceIds);
    traces = readAllTraces(options).filter((trace) => ids.has(trace.traceId));
  } else {
    traces = readAllTraces(options).filter((trace) => trace.filePath === normalizedPath);
  }
  traces = traces.sort(compareTraceTime);
  if (Number.isFinite(limit)) return traces.slice(-limit);
  return traces;
}

function getRecentTraces(filePath, limit = 5, options = {}) {
  return getTracesForFile(filePath, limit, options).slice().reverse();
}

function getTraceChain(traceId, options = {}) {
  const scanOpts = { days: 'all', ...options };
  const all = readAllTraces(scanOpts);
  const byId = new Map(all.map((trace) => [trace.traceId, trace]));
  const chain = [];
  const seen = new Set();
  let current = byId.get(traceId) || null;
  while (current && !seen.has(current.traceId)) {
    seen.add(current.traceId);
    chain.push(current);
    current = current.prevTraceId ? byId.get(current.prevTraceId) || null : null;
  }
  return chain.reverse();
}

function getSessionTraces(sessionId, options = {}) {
  return readAllTraces(options).filter((trace) => trace.sessionId === sessionId || trace.session_id === sessionId).sort(compareTraceTime);
}

function parseArgs(argv) {
  const args = { _: [], json: false, limit: undefined, days: undefined };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json' || arg === '-j') args.json = true;
    else if (arg === '--limit' || arg === '-n') args.limit = Number(argv[++i]);
    else if (arg === '--days' || arg === '-d') args.days = argv[++i];
    else if (arg === '--all' || arg === '-a') args.days = 'all';
    else args._.push(arg);
  }
  return args;
}

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function table(records) {
  if (!records.length) return 'No traces found.\n';
  const header = ['timestamp', 'operation', 'sessionId', 'agentName', 'filePath', 'purpose', 'traceId'];
  const lines = [header.join('\t')];
  for (const trace of records) {
    lines.push(
      [
        trace.timestamp,
        trace.operation,
        trace.sessionId,
        trace.agentName,
        trace.filePath,
        String(trace.purpose || '').replace(/\s+/g, ' ').slice(0, 80),
        trace.traceId,
      ].join('\t'),
    );
  }
  return `${lines.join('\n')}\n`;
}

function usage() {
  return `Usage:\n  node src/trace/trace.js recent <filePath> [--limit 5] [--days 30|all] [--all] [--json]\n  node src/trace/trace.js chain <traceId> [--days 30|all] [--all] [--json]\n  node src/trace/trace.js session <sessionId> [--days 30|all] [--all] [--json]\n`;
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const [cmd, value] = args._;
  const limit = Number.isFinite(args.limit) ? args.limit : 5;
  const scanOptions = { days: args.days };
  try {
    if (cmd === 'recent') {
      if (!value) throw new Error('recent requires <filePath>');
      const traces = getRecentTraces(value, limit, scanOptions);
      if (args.json) printJson({ filePath: normalizeFilePath(value), traces });
      else process.stdout.write(table(traces));
      return 0;
    }
    if (cmd === 'chain') {
      if (!value) throw new Error('chain requires <traceId>');
      const traces = getTraceChain(value, scanOptions);
      if (args.json) printJson({ traceId: value, chain: traces });
      else process.stdout.write(table(traces));
      return traces.length ? 0 : 1;
    }
    if (cmd === 'session') {
      if (!value) throw new Error('session requires <sessionId>');
      const traces = getSessionTraces(value, scanOptions);
      if (args.json) printJson({ sessionId: value, traces });
      else process.stdout.write(table(traces));
      return traces.length ? 0 : 1;
    }
    process.stderr.write(usage());
    return 1;
  } catch (error) {
    process.stderr.write(`trace.js: ${error.message}\n`);
    return 1;
  }
}

module.exports = {
  TRACE_OPERATIONS,
  DEFAULT_TRACE_SCAN_DAYS,
  appendTrace,
  getRecentTraces,
  getTraceChain,
  getSessionTraces,
  getTraceById,
  getTracesForFile,
  normalizeFilePath,
  getStoreHome,
  timelineFileForDate,
  appendTimelineEvent,
  traceFileForDate,
  readAllTraces,
  parseTraceScanDays,
  traceFileDate,
  traceScanStartDate,
  filterTraceFilesByDays,
};

if (require.main === module) {
  process.exitCode = main();
}
