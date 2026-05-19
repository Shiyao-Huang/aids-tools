'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

function tmpHome(name) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `selftools-session-${name}-`));
}

function loadSession(home) {
  process.env.AIDS_HOME = home;
  delete require.cache[require.resolve('../lib/constants')];
  delete require.cache[require.resolve('../lib/session')];
  return require('../lib/session');
}

function runSessionWorker(home, script) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['-e', script], {
      cwd: path.join(__dirname, '..'),
      env: { ...process.env, AIDS_HOME: home },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

// --- register ---

test('register creates new session', () => {
  const home = tmpHome('new');
  const session = loadSession(home);
  const r = session.register({ session_id: 's1', role: 'implementer' });
  assert.equal(r.session_id, 's1');
  assert.equal(r.role, 'implementer');
  assert.equal(r.status, 'active');
  assert.ok(r.started_at);
  assert.ok(r.last_seen_at);
});

test('register merges existing session preserving started_at', () => {
  const home = tmpHome('merge');
  const session = loadSession(home);
  const first = session.register({ session_id: 's1', role: 'impl', display_name: 'Agent1' });
  const originalStart = first.started_at;

  // Small delay to ensure last_seen_at differs
  const merged = session.register({ session_id: 's1', role: 'reviewer', goal: 'review code' });
  assert.equal(merged.role, 'reviewer');
  assert.equal(merged.display_name, 'Agent1'); // preserved from original
  assert.equal(merged.goal, 'review code'); // new field
  assert.equal(merged.started_at, originalStart); // preserved
  assert.ok(merged.last_seen_at >= originalStart);
});

test('register throws without session_id', () => {
  const home = tmpHome('throw');
  const session = loadSession(home);
  assert.throws(() => session.register({}), /session_id is required/);
});

test('register defaults optional fields', () => {
  const home = tmpHome('defaults');
  const session = loadSession(home);
  const r = session.register({ session_id: 's1' });
  assert.equal(r.role, 'unknown');
  assert.equal(r.display_name, '');
  assert.equal(r.task_id, null);
  assert.equal(r.goal, '');
  assert.equal(r.runtime, 'claude');
  assert.equal(r.status, 'active');
});

test('register tolerates concurrent writes for the same session', async () => {
  const home = tmpHome('concurrent-register');
  const workers = Array.from({ length: 8 }, (_, i) => {
    const payload = {
      session_id: 'shared-session',
      role: `role-${i}`,
      display_name: `Agent ${i}`,
      goal: 'x'.repeat(128 * 1024) + `-${i}`,
      started_at: 1000 + i,
    };
    return runSessionWorker(
      home,
      `const session = require('./lib/session'); session.register(${JSON.stringify(payload)});`,
    );
  });

  const results = await Promise.all(workers);
  assert.deepEqual(results.map((result) => result.code), Array(8).fill(0), JSON.stringify(results, null, 2));

  const session = loadSession(home);
  const found = session.lookup('shared-session');
  assert.ok(found);
  assert.equal(found.session_id, 'shared-session');
  assert.equal(found.status, 'active');
  assert.match(found.role, /^role-\d$/);
  assert.match(found.display_name, /^Agent \d$/);
  assert.match(found.goal, /^x+-\d$/);
  assert.ok(found.last_seen_at >= found.started_at);
});

// --- lookup ---

test('lookup returns session by id', () => {
  const home = tmpHome('lookup');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  const found = session.lookup('s1');
  assert.ok(found);
  assert.equal(found.role, 'impl');
});

test('lookup returns null for missing session', () => {
  const home = tmpHome('lookup-miss');
  const session = loadSession(home);
  assert.equal(session.lookup('nonexistent'), null);
});

// --- resolve ---

test('resolve uses env vars when no session file', () => {
  const home = tmpHome('resolve-env');
  const session = loadSession(home);
  process.env.AIDS_ROLE = 'architect';
  process.env.AIDS_INTENT = 'design system';
  const id = session.resolve('test-session');
  assert.equal(id.session_id, 'test-session');
  assert.equal(id.role, 'architect');
  assert.equal(id.goal, 'design system');
  delete process.env.AIDS_ROLE;
  delete process.env.AIDS_INTENT;
});

test('resolve returns unknown when no id or env', () => {
  const home = tmpHome('resolve-unknown');
  const session = loadSession(home);
  const orig = process.env.AIDS_SESSION_ID;
  delete process.env.AIDS_SESSION_ID;
  delete process.env.AID_SESSION_ID;
  delete process.env.SESSION_ID;
  delete process.env.SELFTOOLS_SESSION_ID;
  delete process.env.ZHUYI_SESSION_ID;
  delete process.env.AHA_SESSION_ID;
  const id = session.resolve();
  assert.equal(id.session_id, 'unknown');
  if (orig) process.env.AIDS_SESSION_ID = orig;
});

test('resolve prefers session file over env for role', () => {
  const home = tmpHome('resolve-file');
  const session = loadSession(home);
  session.register({ session_id: 's-file', role: 'qa-engineer' });
  process.env.AIDS_ROLE = 'impl';
  const id = session.resolve('s-file');
  assert.equal(id.role, 'qa-engineer'); // file wins
  delete process.env.AIDS_ROLE;
});

// --- heartbeat ---

test('heartbeat bumps last_seen_at', () => {
  const home = tmpHome('heartbeat');
  const session = loadSession(home);
  const r1 = session.register({ session_id: 's1' });
  const before = r1.last_seen_at;
  const r2 = session.heartbeat('s1');
  assert.ok(r2.last_seen_at >= before);
});

test('multiple heartbeats are monotonic and preserve session metadata', () => {
  const home = tmpHome('heartbeat-multiple');
  const session = loadSession(home);
  const originalNow = Date.now;
  let now = 2000;
  Date.now = () => {
    now += 10;
    return now;
  };
  try {
    session.register({ session_id: 's1', role: 'impl', goal: 'ship feature' });
    const beats = [session.heartbeat('s1'), session.heartbeat('s1'), session.heartbeat('s1')];
    assert.deepEqual(beats.map((beat) => beat.role), ['impl', 'impl', 'impl']);
    assert.deepEqual(beats.map((beat) => beat.goal), ['ship feature', 'ship feature', 'ship feature']);
    assert.ok(beats[0].last_seen_at < beats[1].last_seen_at);
    assert.ok(beats[1].last_seen_at < beats[2].last_seen_at);
  } finally {
    Date.now = originalNow;
  }
});

test('heartbeat returns null for missing', () => {
  const home = tmpHome('heartbeat-miss');
  const session = loadSession(home);
  assert.equal(session.heartbeat('nope'), null);
});

// --- retire ---

test('retire marks session as retired', () => {
  const home = tmpHome('retire');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  const r = session.retire('s1', 'task complete');
  assert.equal(r.status, 'retired');
  assert.equal(r.retire_reason, 'task complete');
  // lookup confirms persistence
  assert.equal(session.lookup('s1').status, 'retired');
});

test('retire returns null for missing', () => {
  const home = tmpHome('retire-miss');
  const session = loadSession(home);
  assert.equal(session.retire('nope'), null);
});

// --- updateGoal ---

test('updateGoal changes task_id and goal', () => {
  const home = tmpHome('goal');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  const r = session.updateGoal('s1', { task_id: 't1', goal: 'fix bug' });
  assert.equal(r.task_id, 't1');
  assert.equal(r.goal, 'fix bug');
});

test('updateGoal partial update only changes provided fields', () => {
  const home = tmpHome('goal-partial');
  const session = loadSession(home);
  session.register({ session_id: 's1', task_id: 't0', goal: 'original' });
  const r = session.updateGoal('s1', { goal: 'updated' });
  assert.equal(r.task_id, 't0'); // unchanged
  assert.equal(r.goal, 'updated');
});

test('updateGoal accepts an explicit empty goal without clearing task_id', () => {
  const home = tmpHome('goal-empty');
  const session = loadSession(home);
  session.register({ session_id: 's1', task_id: 't0', goal: 'original' });
  const r = session.updateGoal('s1', { goal: '' });
  assert.equal(r.task_id, 't0');
  assert.equal(r.goal, '');
  assert.equal(session.lookup('s1').goal, '');
});

// --- listActive ---

test('listActive returns only active sessions', () => {
  const home = tmpHome('active');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  session.register({ session_id: 's2', role: 'reviewer' });
  session.retire('s2');
  const active = session.listActive();
  assert.equal(active.length, 1);
  assert.equal(active[0].session_id, 's1');
});

test('listActive filters by role', () => {
  const home = tmpHome('active-filter');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  session.register({ session_id: 's2', role: 'reviewer' });
  const impls = session.listActive({ role: 'impl' });
  assert.equal(impls.length, 1);
  assert.equal(impls[0].session_id, 's1');
});

// --- listAll ---

test('listAll includes all statuses', () => {
  const home = tmpHome('all');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl' });
  session.register({ session_id: 's2', role: 'reviewer' });
  session.retire('s2');
  const all = session.listAll();
  assert.equal(all.length, 2);
});

// --- whois ---

test('whois returns human-readable summary', () => {
  const home = tmpHome('whois');
  const session = loadSession(home);
  session.register({ session_id: 's1', role: 'impl', display_name: 'TestAgent' });
  const summary = session.whois('s1');
  assert.ok(summary.includes('impl'));
  assert.ok(summary.includes('TestAgent'));
});

test('whois returns unknown for missing session', () => {
  const home = tmpHome('whois-miss');
  const session = loadSession(home);
  const summary = session.whois('nope');
  assert.ok(summary.includes('unknown session'));
});

// --- TOCTOU safety (register overwrites corrupt file) ---

test('register handles corrupt existing file gracefully', () => {
  const home = tmpHome('corrupt');
  const session = loadSession(home);
  // Write corrupt JSON to session file
  fs.mkdirSync(path.join(home, 'sessions'), { recursive: true });
  fs.writeFileSync(path.join(home, 'sessions', 's1.json'), 'NOT JSON{', 'utf-8');
  const r = session.register({ session_id: 's1', role: 'impl' });
  assert.equal(r.session_id, 's1');
  assert.equal(r.status, 'active'); // fresh session, not merge
});
