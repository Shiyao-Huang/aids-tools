#!/usr/bin/env node
'use strict';

/**
 * AIDS (Agent-ID System) — Rating & Feedback Layer
 *
 * Stores post-hoc peer/human evaluation for trace operations at:
 *   ~/.aids/ratings.ndjson
 *
 * Env var precedence: AIDS_* > AID_* > SELFTOOLS_* > ZHUYI_* > CONSCIOUS_TOOLS_*
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {
  getStoreHome,
  getTraceById,
  getTracesForFile,
  getSessionTraces,
  normalizeFilePath,
  appendTimelineEvent,
} = require('../trace/trace');

const VERDICTS = new Set(['good', 'bad', 'neutral', 'uncertain']);
const LOCK_RETRY_MS = 25;
const LOCK_TIMEOUT_MS = 2500;

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
  return dirPath;
}

function ratingsFile() {
  ensureDir(getStoreHome());
  return path.join(getStoreHome(), 'ratings.ndjson');
}

function locksDir() {
  return ensureDir(path.join(getStoreHome(), 'locks'));
}

function newUuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return [4, 2, 2, 2, 6]
    .map((n) => crypto.randomBytes(n).toString('hex'))
    .join('-');
}

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function withLock(name, fn) {
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
      // Best effort.
    }
  }
}

function appendLineAtomic(filePath, record) {
  ensureDir(path.dirname(filePath));
  return withLock(`append-${path.basename(filePath)}`, () => {
    const previous = fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
    const tmp = `${filePath}.${process.pid}.${Date.now()}.tmp`;
    fs.writeFileSync(tmp, previous + `${JSON.stringify(record)}\n`, 'utf8');
    fs.renameSync(tmp, filePath);
    return record;
  });
}

function toIsoTimestamp(value) {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'number') return new Date(value).toISOString();
  if (typeof value === 'string') {
    const n = Number(value);
    if (Number.isFinite(n) && value.trim() !== '') return new Date(n).toISOString();
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return d.toISOString();
  }
  return new Date().toISOString();
}

function envFirst(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

function inferRuntime(input = {}) {
  return String(input.runtime || input.host_runtime || envFirst('AIDS_RUNTIME', 'AID_RUNTIME', 'SELFTOOLS_RUNTIME', 'ZHUYI_RUNTIME', 'RUNTIME') || 'unknown').toLowerCase();
}

function inferActorType(input = {}, runtime = 'unknown') {
  const actorType =
    input.actor_type ||
    input.actorType ||
    input.rater_actor_type ||
    envFirst('AIDS_ACTOR_TYPE', 'AID_ACTOR_TYPE', 'SELFTOOLS_ACTOR_TYPE', 'ZHUYI_ACTOR_TYPE', 'ACTOR_TYPE');
  if (actorType) return String(actorType).toLowerCase();
  if (runtime === 'claude' || runtime === 'codex') return 'agent';
  if (runtime === 'bash') return envFirst('AIDS_SESSION_ID', 'AID_SESSION_ID', 'SESSION_ID', 'SELFTOOLS_SESSION_ID', 'ZHUYI_SESSION_ID') ? 'human' : 'bash';
  return 'unknown';
}

function normalizeRating(input = {}) {
  const verdict = String(input.verdict || input.score || '').toLowerCase();
  const ratedBy =
    input.ratedBy ||
    input.rater_session_id ||
    input.rated_by ||
    process.env.AIDS_SESSION_ID ||
    process.env.AID_SESSION_ID ||
    process.env.SESSION_ID ||
    process.env.SELFTOOLS_SESSION_ID ||
    process.env.ZHUYI_SESSION_ID ||
    'anonymous';
  const runtime = inferRuntime(input);
  const actorType = inferActorType(input, runtime);
  const record = Object.assign({}, input, {
    ratingId: input.ratingId || input.rating_id || newUuid(),
    traceId: input.traceId || input.trace_id,
    ratedBy,
    verdict,
    comment: input.comment == null ? '' : String(input.comment),
    timestamp: toIsoTimestamp(input.timestamp || input.timestamp_iso || new Date()),
    actor_type: actorType,
    runtime,
  });

  // Compatibility aliases.
  record.rating_id = record.ratingId;
  record.trace_id = record.traceId;
  record.rated_by = record.ratedBy;
  record.rater_session_id = record.ratedBy;
  record.score = record.verdict;
  record.actorType = record.actor_type;
  record.rater_actor_type = record.actor_type;
  return record;
}

function validateRating(record, { allowMissingTrace = false } = {}) {
  if (!record.traceId) throw new Error('traceId is required');
  if (!VERDICTS.has(record.verdict)) throw new Error('verdict must be good|bad|neutral|uncertain');
  if (!record.ratedBy) throw new Error('ratedBy is required');
  if (!allowMissingTrace && !getTraceById(record.traceId)) throw new Error(`trace not found: ${record.traceId}`);
}

function addRating(traceId, verdict, comment = '', options = {}) {
  const record = normalizeRating({
    traceId,
    verdict,
    comment,
    ratedBy: options.ratedBy,
    timestamp: options.timestamp,
    runtime: options.runtime,
    actor_type: options.actor_type || options.actorType || options.rater_actor_type,
  });
  validateRating(record, options);
  appendLineAtomic(ratingsFile(), record);
  try { appendTimelineEvent('rating', record); } catch (_) { /* non-blocking */ }
  return record;
}

function readRatingsFile(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const text = fs.readFileSync(filePath, 'utf8');
  if (!text.trim()) return [];
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return normalizeRating(JSON.parse(line));
      } catch (_) {
        return null;
      }
    })
    .filter(Boolean);
}

function readAllRatings() {
  const files = [];
  const root = ratingsFile();
  if (fs.existsSync(root)) files.push(root);
  const legacyDir = path.join(getStoreHome(), 'ratings');
  if (fs.existsSync(legacyDir)) {
    for (const name of fs.readdirSync(legacyDir).sort()) {
      if (name.endsWith('.ndjson') || name.endsWith('.jsonl')) files.push(path.join(legacyDir, name));
    }
  }
  return files.flatMap(readRatingsFile).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
}

function getRatingsForTrace(traceId) {
  return readAllRatings().filter((rating) => rating.traceId === traceId || rating.trace_id === traceId);
}

function emptyCounts() {
  return { good: 0, bad: 0, neutral: 0, total: 0 };
}

function addToCounts(counts, verdict) {
  counts[verdict] = Number(counts[verdict] || 0) + 1;
  counts.total = Number(counts.total || 0) + 1;
}

function getRatingsSummary(filePath) {
  const normalizedPath = normalizeFilePath(filePath);
  const traces = getTracesForFile(normalizedPath, Infinity);
  const allRatings = readAllRatings();
  const byTrace = new Map();
  const counts = emptyCounts();

  for (const trace of traces) {
    byTrace.set(trace.traceId, []);
  }
  for (const rating of allRatings) {
    if (!byTrace.has(rating.traceId)) continue;
    byTrace.get(rating.traceId).push(rating);
    addToCounts(counts, rating.verdict);
  }

  return {
    filePath: normalizedPath,
    traceCount: traces.length,
    ratingCount: counts.total,
    verdicts: counts,
    traces: traces.map((trace) => ({
      traceId: trace.traceId,
      operation: trace.operation,
      sessionId: trace.sessionId,
      agentName: trace.agentName,
      purpose: trace.purpose,
      timestamp: trace.timestamp,
      ratings: byTrace.get(trace.traceId) || [],
    })),
  };
}

function getAgentReputation(sessionId) {
  const traces = getSessionTraces(sessionId);
  const traceIds = new Set(traces.map((trace) => trace.traceId));
  const counts = emptyCounts();
  const ratings = [];
  for (const rating of readAllRatings()) {
    if (!traceIds.has(rating.traceId)) continue;
    ratings.push(rating);
    addToCounts(counts, rating.verdict);
  }
  return {
    sessionId,
    traceCount: traces.length,
    ratingCount: counts.total,
    verdicts: counts,
    score: counts.good - counts.bad,
    positiveRatio: counts.total ? counts.good / counts.total : 0,
    ratings,
  };
}

function parseArgs(argv) {
  const args = { _: [], json: false, allowMissingTrace: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json' || arg === '-j') args.json = true;
    else if (arg === '--allow-missing-trace') args.allowMissingTrace = true;
    else args._.push(arg);
  }
  return args;
}

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function printRatingTable(title, ratings) {
  process.stdout.write(`${title}\n`);
  if (!ratings.length) {
    process.stdout.write('No ratings found.\n');
    return;
  }
  process.stdout.write('timestamp\tverdict\tratedBy\ttraceId\tcomment\n');
  for (const rating of ratings) {
    process.stdout.write(
      [rating.timestamp, rating.verdict, rating.ratedBy, rating.traceId, String(rating.comment || '').replace(/\s+/g, ' ').slice(0, 100)].join('\t') + '\n',
    );
  }
}

function usage() {
  return `Usage:\n  node src/ratings/ratings.js rate <traceId> <good|bad|neutral|uncertain> [comment...] [--json]\n  node src/ratings/ratings.js summary <filePath> [--json]\n  node src/ratings/ratings.js reputation <sessionId> [--json]\n`;
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const [cmd, first, second, ...rest] = args._;
  try {
    if (cmd === 'rate') {
      if (!first || !second) throw new Error('rate requires <traceId> <good|bad|neutral|uncertain> [comment]');
      const rating = addRating(first, second, rest.join(' '), { allowMissingTrace: args.allowMissingTrace });
      if (args.json) printJson(rating);
      else printRatingTable('Recorded rating:', [rating]);
      return 0;
    }
    if (cmd === 'summary') {
      if (!first) throw new Error('summary requires <filePath>');
      const summary = getRatingsSummary(first);
      if (args.json) printJson(summary);
      else {
        process.stdout.write(`Ratings summary for ${summary.filePath}\n`);
        process.stdout.write(`traces=${summary.traceCount} ratings=${summary.ratingCount} good=${summary.verdicts.good} bad=${summary.verdicts.bad} neutral=${summary.verdicts.neutral}\n`);
        for (const trace of summary.traces) {
          process.stdout.write(`- ${trace.traceId} ${trace.operation} by ${trace.sessionId}: ${trace.ratings.length} rating(s)\n`);
        }
      }
      return 0;
    }
    if (cmd === 'reputation') {
      if (!first) throw new Error('reputation requires <sessionId>');
      const reputation = getAgentReputation(first);
      if (args.json) printJson(reputation);
      else {
        process.stdout.write(`Reputation for ${first}\n`);
        process.stdout.write(`traces=${reputation.traceCount} ratings=${reputation.ratingCount} score=${reputation.score} good=${reputation.verdicts.good} bad=${reputation.verdicts.bad} neutral=${reputation.verdicts.neutral}\n`);
      }
      return 0;
    }
    process.stderr.write(usage());
    return 1;
  } catch (error) {
    process.stderr.write(`ratings.js: ${error.message}\n`);
    return 1;
  }
}

module.exports = {
  VERDICTS,
  addRating,
  getRatingsForTrace,
  getRatingsSummary,
  getAgentReputation,
  readAllRatings,
  ratingsFile,
};

if (require.main === module) {
  process.exitCode = main();
}
