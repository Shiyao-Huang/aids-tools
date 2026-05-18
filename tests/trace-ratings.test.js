'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function tmpHome(name) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `selftools-${name}-`));
}

function loadModules(home) {
  process.env.AIDS_HOME = home;
  delete process.env.CONSCIOUS_TOOLS_HOME;
  delete require.cache[require.resolve('../src/trace/trace')];
  delete require.cache[require.resolve('../src/ratings/ratings')];
  const trace = require('../src/trace/trace');
  const ratings = require('../src/ratings/ratings');
  return { trace, ratings };
}

function utcDate(offsetDays = 0) {
  const date = new Date();
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function isoOnDate(date, second = 0) {
  return `${date}T00:00:${String(second).padStart(2, '0')}.000Z`;
}

test('appendTrace stores chain and recent/session queries', () => {
  const home = tmpHome('trace');
  const { trace } = loadModules(home);
  const file = path.join(home, 'workspace', 'doc.md');
  const today = utcDate();

  const first = trace.appendTrace({
    sessionId: 's1',
    agentName: 'Jane',
    role: 'scribe',
    runtime: 'claude',
    operation: 'Read',
    filePath: file,
    purpose: 'observe before editing',
    timestamp: isoOnDate(today, 0),
  });
  const second = trace.appendTrace({
    sessionId: 's2',
    agentName: 'AC',
    role: 'implementer',
    operation: 'Write',
    filePath: file,
    purpose: 'write trace module',
    timestamp: isoOnDate(today, 1),
  });

  assert.equal(second.prevTraceId, first.traceId);
  assert.equal(first.runtime, 'claude');
  assert.equal(first.actor_type, 'agent');
  assert.equal(trace.getRecentTraces(file, 1)[0].traceId, second.traceId);
  assert.deepEqual(trace.getTraceChain(second.traceId).map((item) => item.traceId), [first.traceId, second.traceId]);
  assert.deepEqual(trace.getSessionTraces('s2').map((item) => item.traceId), [second.traceId]);
  assert.ok(fs.existsSync(path.join(home, 'traces', `${today}.ndjson`)));
  const timeline = fs.readFileSync(path.join(home, 'timeline', `${today}.jsonl`), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(timeline[0].schema_version, 'aids.timeline.v1');
  assert.equal(timeline[0].runtime, 'claude');
  assert.equal(timeline[0].actor_type, 'agent');
});

test('trace CLI emits JSON for recent traces', () => {
  const home = tmpHome('trace-cli');
  const { trace } = loadModules(home);
  const file = path.join(home, 'target.txt');
  const appended = trace.appendTrace({ sessionId: 'cli-s', operation: 'Edit', filePath: file, purpose: 'cli check' });

  const result = spawnSync(process.execPath, ['src/trace/trace.js', 'recent', file, '--json'], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, AIDS_HOME: home },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout);
  assert.equal(parsed.traces[0].traceId, appended.traceId);
});

test('non-file tools can leave traces through the shared timeline', () => {
  const home = tmpHome('tool-trace');
  const { trace } = loadModules(home);
  const appended = trace.appendTrace({
    sessionId: 'tool-s',
    operation: 'WebFetch',
    filePath: 'tool:WebFetch',
    purpose: 'fetch external context',
    runtime: 'codex',
  });

  assert.equal(appended.operation, 'WebFetch');
  assert.equal(trace.getRecentTraces('tool:WebFetch', 1)[0].traceId, appended.traceId);
});

test('post hook records non-file tool activity with synthetic tool resource', () => {
  const home = tmpHome('post-hook-tool');
  const result = spawnSync(process.execPath, ['hooks/post_tool_use.js'], {
    cwd: path.join(__dirname, '..'),
    env: {
      ...process.env,
      AIDS_HOME: home,
      AIDS_SESSION_ID: 'web-session',
      AIDS_ROLE: 'researcher',
      AIDS_RUNTIME: 'codex',
      AIDS_INTENT: 'collect current docs',
    },
    input: JSON.stringify({
      tool_name: 'WebFetch',
      tool_input: { url: 'https://example.com' },
      tool_response: { status: 200 },
    }),
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  const { trace } = loadModules(home);
  const traces = trace.getRecentTraces('tool:WebFetch', 1);
  assert.equal(traces[0].sessionId, 'web-session');
  assert.equal(traces[0].operation, 'WebFetch');
});

test('pre hook keeps injected context inside line budget', () => {
  const home = tmpHome('pre-hook-budget');
  const { trace } = loadModules(home);
  const file = path.join(home, 'shared.txt');
  const today = utcDate();
  for (let i = 0; i < 4; i += 1) {
    trace.appendTrace({
      sessionId: `peer-${i}`,
      role: 'agent',
      operation: 'Write',
      filePath: file,
      purpose: `very long purpose ${i} that should be clipped to protect context budget`,
      timestamp: isoOnDate(today, i),
    });
  }

  const result = spawnSync(process.execPath, ['hooks/pre_tool_use.js'], {
    cwd: path.join(__dirname, '..'),
    env: {
      ...process.env,
      AIDS_HOME: home,
      AIDS_SESSION_ID: 'current-agent',
      AIDS_ROLE: 'implementer',
      AIDS_RUNTIME: 'codex',
      AIDS_AWARENESS_LINES: '5',
      AIDS_AWARENESS_CHARS: '48',
    },
    input: JSON.stringify({
      tool_name: 'Write',
      tool_input: { file_path: file },
    }),
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  const lines = result.stderr.trim().split(/\r?\n/);
  assert.ok(lines.length <= 5, result.stderr);
  assert.match(result.stderr, /context lines clipped/);
});

test('readAllTraces defaults to a 30-day scan window with explicit days override', () => {
  const home = tmpHome('trace-days');
  const { trace } = loadModules(home);
  const recentFile = path.join(home, 'recent.txt');
  const oldFile = path.join(home, 'old.txt');
  const recent = trace.appendTrace({
    sessionId: 'recent-session',
    operation: 'Read',
    filePath: recentFile,
    purpose: 'recent trace',
    timestamp: isoOnDate(utcDate(-1), 0),
  });
  const old = trace.appendTrace({
    sessionId: 'old-session',
    operation: 'Read',
    filePath: oldFile,
    purpose: 'old trace outside default window',
    timestamp: isoOnDate(utcDate(-45), 0),
  });

  assert.deepEqual(trace.readAllTraces().map((item) => item.traceId), [recent.traceId]);
  // getTraceById always scans all history (backward compat for lookups by ID)
  assert.equal(trace.getTraceById(old.traceId).traceId, old.traceId);
  assert.equal(trace.getTraceById(old.traceId, { days: 30 }), null);
  assert.equal(trace.getTraceById(old.traceId, { days: 'all' }).traceId, old.traceId);
  assert.deepEqual(trace.getTraceChain(old.traceId).map((item) => item.traceId), [old.traceId]);

  const defaultRecent = spawnSync(process.execPath, ['src/trace/trace.js', 'recent', oldFile, '--json'], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, AIDS_HOME: home },
    encoding: 'utf8',
  });
  assert.equal(defaultRecent.status, 0, defaultRecent.stderr);
  assert.deepEqual(JSON.parse(defaultRecent.stdout).traces, []);

  const allRecent = spawnSync(process.execPath, ['src/trace/trace.js', 'recent', oldFile, '--days', 'all', '--json'], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, AIDS_HOME: home },
    encoding: 'utf8',
  });
  assert.equal(allRecent.status, 0, allRecent.stderr);
  assert.deepEqual(JSON.parse(allRecent.stdout).traces.map((item) => item.traceId), [old.traceId]);

  const allFlagRecent = spawnSync(process.execPath, ['src/trace/trace.js', 'recent', oldFile, '--all', '--json'], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, AIDS_HOME: home },
    encoding: 'utf8',
  });
  assert.equal(allFlagRecent.status, 0, allFlagRecent.stderr);
  assert.deepEqual(JSON.parse(allFlagRecent.stdout).traces.map((item) => item.traceId), [old.traceId]);
});

test('ratings connect verdicts to trace summary and reputation', () => {
  const home = tmpHome('ratings');
  const { trace, ratings } = loadModules(home);
  const file = path.join(home, 'code.js');
  const t1 = trace.appendTrace({ sessionId: 'agent-a', operation: 'Write', filePath: file, purpose: 'create code' });
  const t2 = trace.appendTrace({ sessionId: 'agent-a', operation: 'Edit', filePath: file, purpose: 'refine code' });

  const r1 = ratings.addRating(t1.traceId, 'good', 'useful create', { ratedBy: 'qa' });
  ratings.addRating(t2.traceId, 'bad', 'regression', { ratedBy: 'qa' });

  assert.equal(ratings.getRatingsForTrace(t1.traceId)[0].ratingId, r1.ratingId);
  const summary = ratings.getRatingsSummary(file);
  assert.equal(summary.traceCount, 2);
  assert.equal(summary.verdicts.good, 1);
  assert.equal(summary.verdicts.bad, 1);

  const reputation = ratings.getAgentReputation('agent-a');
  assert.equal(reputation.traceCount, 2);
  assert.equal(reputation.score, 0);
});

test('ratings CLI records a verdict', () => {
  const home = tmpHome('ratings-cli');
  const { trace } = loadModules(home);
  const file = path.join(home, 'review.md');
  const t = trace.appendTrace({ sessionId: 'agent-cli', operation: 'Write', filePath: file, purpose: 'create reviewed file' });

  const result = spawnSync(process.execPath, ['src/ratings/ratings.js', 'rate', t.traceId, 'neutral', 'needs more context', '--json'], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, AIDS_HOME: home, AIDS_SESSION_ID: 'reviewer', AIDS_RUNTIME: 'codex' },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout);
  assert.equal(parsed.traceId, t.traceId);
  assert.equal(parsed.verdict, 'neutral');
  assert.equal(parsed.ratedBy, 'reviewer');
  assert.equal(parsed.runtime, 'codex');
  assert.equal(parsed.actor_type, 'agent');
});
