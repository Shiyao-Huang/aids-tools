'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const PRE_HOOK = path.join(ROOT, 'hooks', 'pre_tool_use.js');
const POST_HOOK = path.join(ROOT, 'hooks', 'post_tool_use.js');

function tmpHome(name) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `selftools-hooks-${name}-`));
}

function runHook(script, input, env) {
  return spawnSync(
    process.execPath, [script],
    {
      input: JSON.stringify(input),
      env: { ...process.env, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 10000,
    },
  );
}

// --- pre_tool_use: basic routing ---

test('pre_tool_use exits 0 for unknown tool', () => {
  const home = tmpHome('pre-unknown');
  const result = runHook(PRE_HOOK,
    { tool_name: 'UnknownTool', tool_input: {} },
    { AIDS_HOME: home, AIDS_RUNTIME: 'claude' },
  );
  assert.equal(result.status, 0);
  assert.equal(result.stderr.trim(), '');
});

test('pre_tool_use exits 0 for Read without traces', () => {
  const home = tmpHome('pre-read');
  const result = runHook(PRE_HOOK,
    { tool_name: 'Read', tool_input: { file_path: '/tmp/nonexistent.txt' } },
    { AIDS_HOME: home, AIDS_RUNTIME: 'claude' },
  );
  assert.equal(result.status, 0);
});

test('pre_tool_use injects context when other session has traces', () => {
  const home = tmpHome('pre-inject');
  // Set up trace data with a trace from another session
  process.env.AIDS_HOME = home;
  delete require.cache[require.resolve('../src/trace/trace')];
  delete require.cache[require.resolve('../lib/constants')];
  const trace = require('../src/trace/trace');

  const testFile = path.join(home, 'workspace', 'target.js');
  trace.appendTrace({
    sessionId: 'other-session-123',
    role: 'reviewer',
    agent_id: 'agent-test',
    agentName: 'Reviewer',
    runtime: 'claude',
    actor_type: 'agent',
    operation: 'Write',
    filePath: testFile,
    purpose: 'review changes',
    result: null,
  });

  // Now run pre hook for Write to same file
  const result = runHook(PRE_HOOK,
    { tool_name: 'Write', tool_input: { file_path: testFile } },
    {
      AIDS_HOME: home,
      AIDS_RUNTIME: 'claude',
      AIDS_SESSION_ID: 'my-session-456',
    },
  );
  assert.equal(result.status, 0);
  assert.ok(result.stderr.includes('AIDS'), `stderr should contain AIDS context, got: ${result.stderr}`);
  assert.ok(result.stderr.includes('reviewer') || result.stderr.includes('other-session'), `should mention other session, got: ${result.stderr}`);
  delete process.env.AIDS_HOME;
});

test('pre_tool_use does not inject for own session', () => {
  const home = tmpHome('pre-self');
  process.env.AIDS_HOME = home;
  delete require.cache[require.resolve('../src/trace/trace')];
  delete require.cache[require.resolve('../lib/constants')];
  const trace = require('../src/trace/trace');

  const testFile = path.join(home, 'workspace', 'mine.js');
  trace.appendTrace({
    sessionId: 'same-session',
    role: 'impl',
    agent_id: 'agent-test',
    agentName: 'Impl',
    runtime: 'claude',
    actor_type: 'agent',
    operation: 'Write',
    filePath: testFile,
    purpose: 'my change',
    result: null,
  });

  const result = runHook(PRE_HOOK,
    { tool_name: 'Write', tool_input: { file_path: testFile } },
    {
      AIDS_HOME: home,
      AIDS_RUNTIME: 'claude',
      AIDS_SESSION_ID: 'same-session',
    },
  );
  assert.equal(result.status, 0);
  // No warning injected for own session
  assert.ok(!result.stderr.includes('AIDS (Agent-ID System)'), `should not warn about own session`);
  delete process.env.AIDS_HOME;
});

test('pre_tool_use Bash command gets lightweight context', () => {
  const home = tmpHome('pre-bash');
  const result = runHook(PRE_HOOK,
    { tool_name: 'Bash', tool_input: { command: 'ls -la /tmp' } },
    { AIDS_HOME: home, AIDS_RUNTIME: 'claude', AIDS_SESSION_ID: 'test-session' },
  );
  assert.equal(result.status, 0);
  assert.ok(result.stderr.includes('AIDS pre-bash'));
});

// --- post_tool_use: basic routing ---

test('post_tool_use exits 0 for unknown tool', () => {
  const home = tmpHome('post-unknown');
  const result = runHook(POST_HOOK,
    { tool_name: 'UnknownTool', tool_input: {}, tool_result: 'ok' },
    { AIDS_HOME: home, AIDS_RUNTIME: 'claude' },
  );
  assert.equal(result.status, 0);
});

test('post_tool_use records trace for Bash', () => {
  const home = tmpHome('post-bash');
  const result = runHook(POST_HOOK,
    { tool_name: 'Bash', tool_input: { command: 'echo hello' }, tool_result: 'hello' },
    {
      AIDS_HOME: home,
      AIDS_RUNTIME: 'claude',
      AIDS_SESSION_ID: 'post-test-session',
    },
  );
  assert.equal(result.status, 0);
  assert.ok(result.stderr.includes('AIDS trace'));
});

test('post_tool_use records trace for Write', () => {
  const home = tmpHome('post-write');
  const result = runHook(POST_HOOK,
    { tool_name: 'Write', tool_input: { file_path: '/tmp/newfile.js' }, tool_result: 'ok' },
    {
      AIDS_HOME: home,
      AIDS_RUNTIME: 'claude',
      AIDS_SESSION_ID: 'post-write-session',
    },
  );
  assert.equal(result.status, 0);
  assert.ok(result.stderr.includes('AIDS trace'));
  assert.ok(result.stderr.includes('Write'));
});

test('post_tool_use extracts error result', () => {
  const home = tmpHome('post-error');
  const result = runHook(POST_HOOK,
    {
      tool_name: 'Bash',
      tool_input: { command: 'false' },
      tool_result: 'Exit code: 1',
      is_error: true,
    },
    {
      AIDS_HOME: home,
      AIDS_RUNTIME: 'claude',
      AIDS_SESSION_ID: 'post-error-session',
    },
  );
  assert.equal(result.status, 0);
});

test('post_tool_use handles null tool_result', () => {
  const home = tmpHome('post-null');
  const result = runHook(POST_HOOK,
    { tool_name: 'Bash', tool_input: { command: 'echo hi' }, tool_result: null },
    { AIDS_HOME: home, AIDS_RUNTIME: 'claude', AIDS_SESSION_ID: 'post-null-session' },
  );
  assert.equal(result.status, 0);
});

test('post_tool_use handles malformed JSON input', () => {
  const home = tmpHome('post-malformed');
  const result = spawnSync(
    process.execPath, [POST_HOOK],
    {
      input: 'not valid json{{{',
      env: { ...process.env, AIDS_HOME: home, AIDS_RUNTIME: 'claude' },
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 10000,
    },
  );
  assert.equal(result.status, 0);
});
