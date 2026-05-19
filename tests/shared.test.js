'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  inferRuntime, inferActorType, resolveAgentId,
  extractResourceKeys, extractBashResources,
  budgetInt, formatAgo, clip, budgetLines,
} = require('../hooks/_aid_shared');

// --- inferRuntime ---

test('inferRuntime returns env AIDS_RUNTIME first', () => {
  process.env.AIDS_RUNTIME = 'claude';
  assert.equal(inferRuntime(), 'claude');
  delete process.env.AIDS_RUNTIME;
});

test('inferRuntime falls back through env chain', () => {
  delete process.env.AIDS_RUNTIME;
  delete process.env.AID_RUNTIME;
  delete process.env.SELFTOOLS_RUNTIME;
  delete process.env.ZHUYI_RUNTIME;
  assert.equal(inferRuntime(), 'unknown');
  process.env.SELFTOOLS_RUNTIME = 'bash';
  assert.equal(inferRuntime(), 'bash');
  delete process.env.SELFTOOLS_RUNTIME;
});

// --- inferActorType ---

test('inferActorType returns explicit env var', () => {
  process.env.AIDS_ACTOR_TYPE = 'custom';
  assert.equal(inferActorType('unknown'), 'custom');
  delete process.env.AIDS_ACTOR_TYPE;
});

test('inferActorType infers agent for claude/codex', () => {
  assert.equal(inferActorType('claude'), 'agent');
  assert.equal(inferActorType('codex'), 'agent');
});

test('inferActorType infers human for bash with session', () => {
  process.env.AIDS_SESSION_ID = 'test-session';
  assert.equal(inferActorType('bash'), 'human');
  delete process.env.AIDS_SESSION_ID;
});

test('inferActorType infers bash for bash without session', () => {
  delete process.env.AIDS_SESSION_ID;
  assert.equal(inferActorType('bash'), 'bash');
});

// --- resolveAgentId ---

test('resolveAgentId uses env var first', () => {
  process.env.AIDS_AGENT_ID = 'my-agent-id';
  const id = resolveAgentId({ session_id: 's1' });
  assert.equal(id, 'my-agent-id');
  delete process.env.AIDS_AGENT_ID;
});

test('resolveAgentId computes deterministic hash from identity', () => {
  delete process.env.AIDS_AGENT_ID;
  delete process.env.AID_AGENT_ID;
  delete process.env.SELFTOOLS_AGENT_ID;
  delete process.env.ZHUYI_AGENT_ID;
  const id1 = resolveAgentId({ display_name: 'Impl', role: 'impl', team_id: 'team1' });
  const id2 = resolveAgentId({ display_name: 'Impl', role: 'impl', team_id: 'team1' });
  assert.ok(id1.startsWith('agent-'));
  assert.equal(id1, id2); // deterministic
});

test('resolveAgentId differs for different identity', () => {
  delete process.env.AIDS_AGENT_ID;
  delete process.env.AID_AGENT_ID;
  delete process.env.SELFTOOLS_AGENT_ID;
  delete process.env.ZHUYI_AGENT_ID;
  const id1 = resolveAgentId({ display_name: 'A', role: 'impl', team_id: 't' });
  const id2 = resolveAgentId({ display_name: 'B', role: 'impl', team_id: 't' });
  assert.notEqual(id1, id2);
});

// --- extractResourceKeys ---

test('extractResourceKeys returns file path for Write tool', () => {
  const keys = extractResourceKeys('Write', { file_path: '/tmp/test.js' });
  assert.deepEqual(keys, ['/tmp/test.js']);
});

test('extractResourceKeys returns file path for Read tool using path key', () => {
  const keys = extractResourceKeys('Read', { path: '/tmp/file.py' });
  assert.deepEqual(keys, ['/tmp/file.py']);
});

test('extractResourceKeys returns empty for tool without path', () => {
  const keys = extractResourceKeys('Grep', { pattern: 'todo' });
  assert.deepEqual(keys, []);
});

test('extractResourceKeys delegates Bash to extractBashResources', () => {
  const keys = extractResourceKeys('Bash', { command: 'cat /tmp/f.txt' });
  assert.ok(keys.length >= 1);
  assert.ok(keys[0].startsWith('bash:'));
});

// --- extractBashResources edge cases ---

test('extractBashResources returns empty for empty command', () => {
  assert.deepEqual(extractBashResources(''), []);
  assert.deepEqual(extractBashResources(null), []);
  assert.deepEqual(extractBashResources(undefined), []);
});

test('extractBashResources always includes bash:hash as first element', () => {
  const keys = extractBashResources('echo hello');
  assert.equal(keys.length, 1);
  assert.ok(keys[0].startsWith('bash:'));
  assert.equal(keys[0].length, 21); // 'bash:' + 16 hex chars
});

test('extractBashResources detects redirect target', () => {
  const keys = extractBashResources('echo hello > /tmp/out.txt');
  assert.ok(keys.some(k => k.includes('out.txt')));
});

test('extractBashResources detects append redirect target', () => {
  const keys = extractBashResources('echo data >> /tmp/log.txt');
  assert.ok(keys.some(k => k.includes('log.txt')));
});

test('extractBashResources detects tee target', () => {
  const keys = extractBashResources('echo data | tee /tmp/tee.txt');
  assert.ok(keys.some(k => k.includes('tee.txt')));
});

test('extractBashResources detects mv target', () => {
  const keys = extractBashResources('mv /tmp/a.txt /tmp/b.txt');
  assert.ok(keys.some(k => k.includes('b.txt')));
});

test('extractBashResources detects cp target', () => {
  const keys = extractBashResources('cp /tmp/a.txt /tmp/b.txt');
  assert.ok(keys.some(k => k.includes('b.txt')));
});

test('extractBashResources pipe chain: detects read targets', () => {
  const keys = extractBashResources('cat /tmp/a.txt | grep pattern | sort');
  assert.ok(keys.some(k => k.includes('a.txt')));
});

test('extractBashResources subshell: detects redirect inside $(...)', () => {
  const keys = extractBashResources('echo $(cat /tmp/x.txt) > /tmp/out.txt');
  assert.ok(keys.some(k => k.includes('out.txt')));
});

test('extractBashResources skips sed -i (mutation)', () => {
  const keys = extractBashResources("sed -i 's/old/new/' /tmp/file.txt");
  // sed -i is excluded from read-only detection
  const fileKeys = keys.filter(k => k.includes('file.txt'));
  assert.equal(fileKeys.length, 0);
});

test('extractBashResources detects cat read target', () => {
  const keys = extractBashResources('cat /tmp/readme.md');
  assert.ok(keys.some(k => k.includes('readme.md')));
});

test('extractBashResources skips flags as file paths', () => {
  const keys = extractBashResources('grep -r "pattern" /tmp/dir/');
  // Should have bash:hash + /tmp/dir/ but not -r
  assert.ok(!keys.some(k => k === '-r'));
});

test('extractBashResources skips /dev/null', () => {
  const keys = extractBashResources('cat /dev/null');
  // Only bash:hash, /dev/null is filtered
  const devKeys = keys.filter(k => k.includes('dev/null'));
  assert.equal(devKeys.length, 0);
});

test('extractBashResources handles quoted redirect target', () => {
  const keys = extractBashResources('echo hi > "/tmp/quoted file.txt"');
  // Should parse the quoted part
  assert.ok(keys.some(k => k.includes('quoted')));
});

test('extractBashResources handles long command (>500 chars)', () => {
  const cmd = 'echo ' + 'x'.repeat(600) + ' > /tmp/big.txt';
  const keys = extractBashResources(cmd);
  assert.ok(keys[0].startsWith('bash:'));
  assert.ok(keys.some(k => k.includes('big.txt')));
});

test('extractBashResources detects known extensionless filenames', () => {
  const keys = extractBashResources('cat Makefile');
  assert.ok(keys.some(k => k.includes('Makefile')));
});

test('extractBashResources ignores heredoc body while keeping redirect target', () => {
  const keys = extractBashResources("cat <<'EOF' > /tmp/heredoc.txt\ncat /tmp/body.txt\nEOF");
  assert.ok(keys.includes('/tmp/heredoc.txt'));
  assert.ok(!keys.some(k => k.includes('body.txt')));
  const pathKeys = keys.filter(k => !k.startsWith('bash:'));
  assert.equal(new Set(pathKeys).size, pathKeys.length);
});

test('extractBashResources trims process substitution read targets', () => {
  const keys = extractBashResources('diff <(sort /tmp/proc-a.txt) <(sort /tmp/proc-b.txt)');
  assert.ok(keys.includes('/tmp/proc-a.txt'));
  assert.ok(keys.includes('/tmp/proc-b.txt'));
  assert.ok(!keys.some(k => k.endsWith('proc-a.txt)')));
  assert.ok(!keys.some(k => k.endsWith('proc-b.txt)')));
});

test('extractBashResources detects xargs read targets from pipeline input', () => {
  const keys = extractBashResources('printf "%s\\n" /tmp/xargs-input.txt | xargs cat');
  assert.ok(keys.includes('/tmp/xargs-input.txt'));
});

test('extractBashResources detects find -exec search roots without glob false positives', () => {
  const keys = extractBashResources('find /tmp/project -name "*.js" -exec grep TODO {} \\;');
  assert.ok(keys.includes('/tmp/project'));
  assert.ok(!keys.some(k => k.includes('*.js')));
});

test('extractBashResources handles inline env vars used in command paths', () => {
  const keys = extractBashResources('AIDS_TEST_DIR=/tmp/aids-env cat "$AIDS_TEST_DIR/input.txt"');
  assert.ok(keys.includes('/tmp/aids-env/input.txt'));
  assert.ok(!keys.some(k => k.includes('AIDS_TEST_DIR=')));
});

// --- budgetInt ---

test('budgetInt returns fallback when no env', () => {
  delete process.env.AIDS_TEST_VAR;
  delete process.env.AID_TEST_VAR;
  assert.equal(budgetInt('AIDS_TEST_VAR', 5, 1, 20), 5);
});

test('budgetInt clamps to range', () => {
  process.env.AIDS_TEST_VAR = '100';
  assert.equal(budgetInt('AIDS_TEST_VAR', 5, 1, 20), 20);
  delete process.env.AIDS_TEST_VAR;
});

test('budgetInt floors and clamps low', () => {
  process.env.AIDS_TEST_VAR = '-5';
  assert.equal(budgetInt('AIDS_TEST_VAR', 5, 1, 20), 1);
  delete process.env.AIDS_TEST_VAR;
});

// --- formatAgo ---

test('formatAgo shows seconds', () => {
  const ts = new Date(Date.now() - 5000).toISOString();
  assert.ok(formatAgo(ts).includes('s ago'));
});

test('formatAgo shows minutes', () => {
  const ts = new Date(Date.now() - 120000).toISOString();
  assert.ok(formatAgo(ts).includes('m ago'));
});

test('formatAgo shows hours', () => {
  const ts = new Date(Date.now() - 7200000).toISOString();
  assert.ok(formatAgo(ts).includes('h ago'));
});

test('formatAgo handles invalid input gracefully', () => {
  const result = formatAgo('not-a-date');
  // Invalid date produces NaN diff, falls through to hours branch
  assert.ok(typeof result === 'string');
});

// --- clip ---

test('clip returns text within budget', () => {
  assert.equal(clip('hello', 10), 'hello');
});

test('clip truncates with ellipsis', () => {
  const result = clip('hello world this is long', 10);
  assert.ok(result.endsWith('…'));
  assert.ok(result.length <= 10);
});

test('clip handles null/undefined', () => {
  assert.equal(clip(null, 10), '');
  assert.equal(clip(undefined, 10), '');
});

test('clip collapses whitespace', () => {
  assert.equal(clip('hello\n\n  world', 50), 'hello world');
});

// --- budgetLines ---

test('budgetLines returns all lines when under budget', () => {
  const lines = ['a', 'b', 'c'];
  assert.deepEqual(budgetLines(lines, 5), ['a', 'b', 'c']);
});

test('budgetLines clips with summary line', () => {
  const lines = ['a', 'b', 'c', 'd', 'e'];
  const result = budgetLines(lines, 3);
  assert.equal(result.length, 3);
  assert.ok(result[2].includes('clipped'));
});
