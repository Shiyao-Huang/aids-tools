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

test('appendTrace stores chain and recent/session queries', () => {
  const home = tmpHome('trace');
  const { trace } = loadModules(home);
  const file = path.join(home, 'workspace', 'doc.md');

  const first = trace.appendTrace({
    sessionId: 's1',
    agentName: 'Jane',
    role: 'scribe',
    runtime: 'claude',
    operation: 'Read',
    filePath: file,
    purpose: 'observe before editing',
    timestamp: '2026-05-18T00:00:00.000Z',
  });
  const second = trace.appendTrace({
    sessionId: 's2',
    agentName: 'AC',
    role: 'implementer',
    operation: 'Write',
    filePath: file,
    purpose: 'write trace module',
    timestamp: '2026-05-18T00:00:01.000Z',
  });

  assert.equal(second.prevTraceId, first.traceId);
  assert.equal(first.runtime, 'claude');
  assert.equal(first.actor_type, 'agent');
  assert.equal(trace.getRecentTraces(file, 1)[0].traceId, second.traceId);
  assert.deepEqual(trace.getTraceChain(second.traceId).map((item) => item.traceId), [first.traceId, second.traceId]);
  assert.deepEqual(trace.getSessionTraces('s2').map((item) => item.traceId), [second.traceId]);
  assert.ok(fs.existsSync(path.join(home, 'traces', '2026-05-18.ndjson')));
  const timeline = fs.readFileSync(path.join(home, 'timeline', '2026-05-18.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
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
