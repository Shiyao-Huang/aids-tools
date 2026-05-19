/**
 * AIDS (Agent-ID System) — Shared utilities for pre/post tool-use hooks.
 *
 * Provides: inferRuntime, inferActorType, resolveAgentId,
 *           extractResourceKeys, extractBashResources, budgetInt,
 *           formatAgo, clip, budgetLines
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { normalizeFilePath } = require('../src/trace/trace');

// --- Identity helpers ---

function inferRuntime() {
  return process.env.AIDS_RUNTIME ||
         process.env.AID_RUNTIME ||
         process.env.SELFTOOLS_RUNTIME ||
         process.env.ZHUYI_RUNTIME ||
         'unknown';
}

function inferActorType(runtime) {
  const explicit = process.env.AIDS_ACTOR_TYPE ||
                   process.env.AID_ACTOR_TYPE ||
                   process.env.SELFTOOLS_ACTOR_TYPE ||
                   process.env.ZHUYI_ACTOR_TYPE;
  if (explicit) return explicit;
  if (runtime === 'claude' || runtime === 'codex') return 'agent';
  if (runtime === 'bash') return process.env.AIDS_SESSION_ID ? 'human' : 'bash';
  return 'unknown';
}

/**
 * Resolve agent_id: env var → session file → compute from identity fields.
 */
function resolveAgentId(identity) {
  const fromEnv = process.env.AIDS_AGENT_ID ||
                  process.env.AID_AGENT_ID ||
                  process.env.SELFTOOLS_AGENT_ID ||
                  process.env.ZHUYI_AGENT_ID;
  if (fromEnv) return fromEnv;

  if (identity.session_id && identity.session_id !== 'unknown') {
    try {
      const sessionPath = path.join(os.homedir(), '.aids', 'sessions', `${identity.session_id}.json`);
      if (fs.existsSync(sessionPath)) {
        const record = JSON.parse(fs.readFileSync(sessionPath, 'utf-8'));
        if (record.agent_id) return record.agent_id;
      }
    } catch { /* fall through */ }
  }

  const input = `${identity.display_name || ''}:${identity.role || ''}:${identity.team_id || ''}`;
  return 'agent-' + crypto.createHash('sha256').update(input).digest('hex').slice(0, 16);
}

// --- Resource extraction ---

const BASH_COMMAND_SEPARATORS = new Set(['|', ';', '&&', '||']);
const BASH_WRITE_REDIRECTS = new Set(['>', '>>', '1>', '1>>', '2>', '2>>', '&>', '&>>']);
const BASH_READ_REDIRECTS = new Set(['<', '0<']);
const BASH_HEREDOC_REDIRECTS = new Set(['<<', '<<-']);
const BASH_READ_COMMANDS = new Set([
  'cat', 'head', 'tail', 'less', 'more', 'wc', 'sort', 'uniq',
  'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack',
  'sed', 'awk', 'diff', 'comm', 'cut', 'tr',
  'file', 'stat', 'md5sum', 'sha256sum', 'sha1sum', 'shasum',
  'strings', 'hexdump', 'xxd', 'od',
]);
const BASH_READ_VALUE_FLAGS = new Set([
  '-e', '--regexp', '-f', '--file', '--color', '--colour',
  '--exclude', '--include', '--exclude-dir',
  '-n', '--lines', '-c', '--bytes',
  '-k', '--key', '-t', '--field-separator', '-o', '--output',
  '-F', '-v',
  '-d', '--delimiter',
  '--label', '-L', '-U', '--unified',
  '-i', '--in-place',
]);
const BASH_FIND_VALUE_FLAGS = new Set([
  '-name', '-iname', '-path', '-ipath', '-regex', '-iregex',
  '-type', '-maxdepth', '-mindepth', '-newer', '-user', '-group',
  '-perm', '-size', '-mtime', '-mmin', '-ctime', '-cmin', '-atime',
  '-amin', '-exec', '-execdir',
]);
const BASH_XARGS_VALUE_FLAGS = new Set([
  '-I', '--replace', '-n', '--max-args', '-P', '--max-procs',
  '-s', '--max-chars', '-d', '--delimiter', '-E', '--eof',
  '-L', '--max-lines',
]);
const BASH_SPECIAL_PATHS = new Set([
  '/dev/null', '/dev/zero', '/dev/random', '/dev/urandom', '-',
]);
const BASH_KNOWN_FILES = new Set([
  'Makefile', 'Dockerfile', 'README', 'LICENSE', 'CHANGELOG',
  'Rakefile', 'Gemfile', 'Vagrantfile', 'Jenkinsfile',
]);

/**
 * Extract stable resource keys from tool input.
 * File tools → [file path]. Bash → [bash:hash] + parsed file paths.
 */
function extractResourceKeys(toolName, toolInput) {
  if (toolName === 'Bash') {
    return extractBashResources(toolInput.command || '');
  }
  const fp = toolInput.file_path || toolInput.path || '';
  return fp ? [fp] : [];
}

/**
 * Parse Bash command to detect file-mutation patterns and read targets.
 * Returns array: [bash:hash, ...parsedFilePaths].
 */
function extractBashResources(command) {
  if (!command) return [];
  const results = [];
  const seen = new Set();
  const hash = crypto.createHash('sha256').update(command).digest('hex').slice(0, 16);

  const addRaw = (resource) => {
    if (!resource || seen.has(resource)) return;
    seen.add(resource);
    results.push(resource);
  };
  const addPath = (target, env = {}) => {
    const clean = cleanBashPathToken(target, env);
    if (!clean || isSpecialBashPath(clean)) return;
    try { addRaw(normalizeFilePath(clean)); } catch { /* skip invalid paths */ }
  };

  addRaw(`bash:${hash}`);
  collectBashResources(String(command), addPath, {}, 0);

  return results;
}

function collectBashResources(command, addPath, inheritedEnv = {}, depth = 0) {
  if (!command || depth > 6) return;
  const withoutHeredocs = stripBashHeredocBodies(command);
  const { command: scrubbedCommand, subcommands } = extractBashSubcommands(withoutHeredocs);
  for (const subcommand of subcommands) {
    collectBashResources(subcommand, addPath, inheritedEnv, depth + 1);
  }

  const tokens = tokenizeBash(scrubbedCommand);
  const segments = splitBashSegments(tokens);
  for (let i = 0; i < segments.length; i += 1) {
    collectBashWriteResources(segments[i], addPath, inheritedEnv);
    collectBashReadResources(segments[i], addPath, inheritedEnv, segments.slice(0, i), depth);
  }
}

function stripBashHeredocBodies(command) {
  const lines = String(command).split(/\r?\n/);
  const out = [];
  const pending = [];

  for (const line of lines) {
    if (pending.length) {
      const expected = pending[0];
      if (line.trim() === expected || line.replace(/^\t+/, '').trim() === expected) {
        pending.shift();
      }
      continue;
    }

    out.push(line);
    const tokens = tokenizeBash(line);
    for (let i = 0; i < tokens.length; i += 1) {
      const tok = tokens[i];
      if (BASH_HEREDOC_REDIRECTS.has(tok) && tokens[i + 1]) {
        pending.push(cleanHeredocDelimiter(tokens[i + 1]));
        i += 1;
      }
    }
  }

  return out.join('\n');
}

function cleanHeredocDelimiter(token) {
  return String(token || '').replace(/^['"]|['"]$/g, '').trim();
}

function extractBashSubcommands(command) {
  const subcommands = [];
  let scrubbed = '';
  let i = 0;

  while (i < command.length) {
    const ch = command[i];
    const next = command[i + 1];
    const isProcessSub = (ch === '<' || ch === '>') && next === '(';
    const isCommandSub = ch === '$' && next === '(' && command[i + 2] !== '(';
    if (isProcessSub || isCommandSub) {
      const openIndex = i + 1;
      const closeIndex = findMatchingParen(command, openIndex);
      if (closeIndex !== -1) {
        subcommands.push(command.slice(openIndex + 1, closeIndex));
        scrubbed += ' ';
        i = closeIndex + 1;
        continue;
      }
    }
    scrubbed += ch;
    i += 1;
  }

  return { command: scrubbed, subcommands };
}

function findMatchingParen(input, openIndex) {
  let depth = 0;
  let quote = null;
  for (let i = openIndex; i < input.length; i += 1) {
    const ch = input[i];
    if (quote) {
      if (ch === '\\' && quote === '"' && i + 1 < input.length) {
        i += 1;
        continue;
      }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '(') depth += 1;
    if (ch === ')') {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

function tokenizeBash(input) {
  const tokens = [];
  let current = '';
  let quote = null;

  const flush = () => {
    if (current !== '') {
      tokens.push(current);
      current = '';
    }
  };
  const pushOp = (op) => {
    flush();
    tokens.push(op);
  };

  for (let i = 0; i < String(input).length; i += 1) {
    const ch = input[i];
    const next = input[i + 1];
    const third = input[i + 2];

    if (quote) {
      if (ch === '\\' && quote === '"' && i + 1 < input.length) {
        current += input[i + 1];
        i += 1;
        continue;
      }
      if (ch === quote) {
        quote = null;
        continue;
      }
      current += ch;
      continue;
    }

    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '\\' && i + 1 < input.length) {
      current += input[i + 1];
      i += 1;
      continue;
    }
    if (/\s/.test(ch)) {
      flush();
      continue;
    }
    if (ch === '&' && next === '&') {
      pushOp('&&');
      i += 1;
      continue;
    }
    if (ch === '|' && next === '|') {
      pushOp('||');
      i += 1;
      continue;
    }
    if (ch === '|') {
      pushOp('|');
      continue;
    }
    if (ch === ';') {
      pushOp(';');
      continue;
    }
    if (ch === '&' && next === '>' && third === '>') {
      pushOp('&>>');
      i += 2;
      continue;
    }
    if (ch === '&' && next === '>') {
      pushOp('&>');
      i += 1;
      continue;
    }
    if ((ch === '1' || ch === '2' || ch === '0') && next === '>' && third === '>') {
      pushOp(`${ch}>>`);
      i += 2;
      continue;
    }
    if ((ch === '1' || ch === '2' || ch === '0') && (next === '>' || next === '<')) {
      pushOp(`${ch}${next}`);
      i += 1;
      continue;
    }
    if (ch === '<' && next === '<' && third === '-') {
      pushOp('<<-');
      i += 2;
      continue;
    }
    if (ch === '<' && next === '<') {
      pushOp('<<');
      i += 1;
      continue;
    }
    if (ch === '>' && next === '>') {
      pushOp('>>');
      i += 1;
      continue;
    }
    if (ch === '<' || ch === '>') {
      pushOp(ch);
      continue;
    }
    current += ch;
  }

  flush();
  return tokens;
}

function splitBashSegments(tokens) {
  const segments = [];
  let current = [];
  for (const tok of tokens) {
    if (BASH_COMMAND_SEPARATORS.has(tok)) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(tok);
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

function collectBashWriteResources(segment, addPath, inheritedEnv) {
  if (!segment.length) return;
  const { index: commandIndex, env } = consumeBashCommandPrefix(segment, inheritedEnv);

  for (let i = 0; i < segment.length; i += 1) {
    const tok = segment[i];
    if (BASH_WRITE_REDIRECTS.has(tok)) {
      if (segment[i + 1]) addPath(segment[i + 1], env);
      i += 1;
      continue;
    }
    if (BASH_HEREDOC_REDIRECTS.has(tok) || BASH_READ_REDIRECTS.has(tok)) {
      i += 1;
      continue;
    }
    const attachedTarget = attachedBashWriteRedirectTarget(tok);
    if (attachedTarget) addPath(attachedTarget, env);
  }

  const base = path.basename(segment[commandIndex] || '');
  if (base === 'tee') {
    for (let i = commandIndex + 1; i < segment.length; i += 1) {
      const tok = segment[i];
      if (tok === '--') continue;
      if (tok.startsWith('-')) continue;
      addPath(tok, env);
    }
  } else if (base === 'mv' || base === 'cp') {
    const operands = [];
    for (let i = commandIndex + 1; i < segment.length; i += 1) {
      const tok = segment[i];
      if (tok === '--') continue;
      if (tok.startsWith('-')) continue;
      operands.push(tok);
    }
    if (operands.length >= 2) addPath(operands[operands.length - 1], env);
  }
}

function collectBashReadResources(segment, addPath, inheritedEnv, previousSegments, depth) {
  if (!segment.length) return;
  const { index: commandIndex, env } = consumeBashCommandPrefix(segment, inheritedEnv);
  collectBashReadRedirects(segment, addPath, env);

  const base = path.basename(segment[commandIndex] || '');
  if (!base) return;
  if (base === 'find') {
    collectFindResources(segment, commandIndex, addPath, env, depth);
  } else if (base === 'xargs') {
    collectXargsResources(segment, commandIndex, addPath, env, previousSegments);
  } else if (BASH_READ_COMMANDS.has(base)) {
    collectReadCommandArgs(base, segment.slice(commandIndex + 1), addPath, env);
  }
}

function collectBashReadRedirects(segment, addPath, env) {
  for (let i = 0; i < segment.length; i += 1) {
    const tok = segment[i];
    if (BASH_READ_REDIRECTS.has(tok)) {
      if (segment[i + 1]) addPath(segment[i + 1], env);
      i += 1;
    } else if (BASH_HEREDOC_REDIRECTS.has(tok) || BASH_WRITE_REDIRECTS.has(tok)) {
      i += 1;
    }
  }
}

function collectFindResources(segment, commandIndex, addPath, env, depth) {
  let i = commandIndex + 1;
  while (i < segment.length) {
    const tok = segment[i];
    if (tok === '-exec' || tok === '-execdir' || tok.startsWith('-') || tok === '!' || tok === '(' || tok === ')') break;
    if (looksLikeBashFileToken(tok, env)) addPath(tok, env);
    i += 1;
  }

  while (i < segment.length) {
    const tok = segment[i];
    if (tok === '-exec' || tok === '-execdir') {
      const execTokens = [];
      i += 1;
      while (i < segment.length && segment[i] !== ';' && segment[i] !== '+') {
        if (segment[i] !== '{}') execTokens.push(segment[i]);
        i += 1;
      }
      if (execTokens.length) collectBashResources(execTokens.join(' '), addPath, env, depth + 1);
      continue;
    }
    if (BASH_FIND_VALUE_FLAGS.has(tok) || tok.includes('=')) {
      i += 2;
      continue;
    }
    i += 1;
  }
}

function collectXargsResources(segment, commandIndex, addPath, env, previousSegments) {
  let i = commandIndex + 1;
  while (i < segment.length) {
    const tok = segment[i];
    if (tok === '--') {
      i += 1;
      break;
    }
    if (tok === '-a' || tok === '--arg-file') {
      if (segment[i + 1]) addPath(segment[i + 1], env);
      i += 2;
      continue;
    }
    if (BASH_XARGS_VALUE_FLAGS.has(tok) || tok.includes('=')) {
      i += 2;
      continue;
    }
    if (tok.startsWith('-')) {
      i += 1;
      continue;
    }
    break;
  }

  const base = path.basename(segment[i] || 'echo');
  if (!BASH_READ_COMMANDS.has(base)) return;
  const explicitCount = collectReadCommandArgs(base, segment.slice(i + 1), addPath, env);
  if (explicitCount > 0) return;

  const previous = previousSegments[previousSegments.length - 1] || [];
  collectPathLiteralsFromSegment(previous, addPath, env);
}

function collectReadCommandArgs(base, args, addPath, env) {
  if (base === 'sed' && args.some(t => t === '-i' || t === '--in-place' || /^-[^-e]*i/.test(t))) return 0;

  let count = 0;
  let skip = false;
  for (let i = 0; i < args.length; i += 1) {
    const tok = args[i];
    if (skip) {
      skip = false;
      continue;
    }
    if (BASH_WRITE_REDIRECTS.has(tok) || BASH_READ_REDIRECTS.has(tok) || BASH_HEREDOC_REDIRECTS.has(tok)) {
      skip = true;
      continue;
    }
    if (BASH_READ_VALUE_FLAGS.has(tok) || flagHasInlineValue(tok)) {
      skip = !tok.includes('=');
      continue;
    }
    if (tok === '--') continue;
    if (tok.startsWith('-')) continue;
    if (tok === '{}') continue;
    if (looksLikeBashFileToken(tok, env)) {
      addPath(tok, env);
      count += 1;
    }
  }
  return count;
}

function collectPathLiteralsFromSegment(segment, addPath, env) {
  if (!segment.length) return;
  const { index: commandIndex, env: localEnv } = consumeBashCommandPrefix(segment, env);
  let skip = false;
  for (let i = commandIndex + 1; i < segment.length; i += 1) {
    const tok = segment[i];
    if (skip) {
      skip = false;
      continue;
    }
    if (BASH_WRITE_REDIRECTS.has(tok) || BASH_READ_REDIRECTS.has(tok) || BASH_HEREDOC_REDIRECTS.has(tok)) {
      skip = true;
      continue;
    }
    if (BASH_READ_VALUE_FLAGS.has(tok) || BASH_FIND_VALUE_FLAGS.has(tok) || BASH_XARGS_VALUE_FLAGS.has(tok) || flagHasInlineValue(tok)) {
      skip = !tok.includes('=');
      continue;
    }
    if (tok.startsWith('-') || tok === '{}') continue;
    if (looksLikeBashFileToken(tok, localEnv)) addPath(tok, localEnv);
  }
}

function consumeBashCommandPrefix(segment, inheritedEnv = {}) {
  const env = { ...inheritedEnv };
  let index = 0;

  while (index < segment.length && isBashAssignment(segment[index])) {
    applyBashAssignment(segment[index], env);
    index += 1;
  }

  if (path.basename(segment[index] || '') === 'env') {
    index += 1;
    while (index < segment.length && segment[index].startsWith('-')) {
      index += 1;
    }
    while (index < segment.length && isBashAssignment(segment[index])) {
      applyBashAssignment(segment[index], env);
      index += 1;
    }
  }

  return { index, env };
}

function isBashAssignment(token) {
  return /^[A-Za-z_][A-Za-z0-9_]*=/.test(String(token || ''));
}

function applyBashAssignment(token, env) {
  const idx = token.indexOf('=');
  if (idx <= 0) return;
  const name = token.slice(0, idx);
  const raw = token.slice(idx + 1);
  env[name] = expandBashVariables(raw, env).value;
}

function expandBashVariables(value, env = {}) {
  let unresolved = false;
  const text = String(value || '').replace(/\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))/g, (match, braced, bare) => {
    const name = braced || bare;
    if (Object.prototype.hasOwnProperty.call(env, name)) return env[name];
    if (Object.prototype.hasOwnProperty.call(process.env, name)) return process.env[name];
    unresolved = true;
    return match;
  });
  return { value: text, unresolved };
}

function cleanBashPathToken(token, env = {}) {
  if (token === null || token === undefined) return '';
  let value = String(token).trim();
  if (!value || BASH_COMMAND_SEPARATORS.has(value) || value === '{}') return '';
  if (isBashAssignment(value)) return '';
  value = value.replace(/^[<(]+/, '').replace(/[)>]+$/g, '');
  value = value.replace(/^[`'"]|[`'"]$/g, '');
  value = value.replace(/[,\]]+$/g, '');
  const expanded = expandBashVariables(value, env);
  if (expanded.unresolved) return '';
  value = expanded.value.trim();
  if (!value || value === '{}' || isBashAssignment(value)) return '';
  return value;
}

function looksLikeBashFileToken(token, env = {}) {
  const clean = cleanBashPathToken(token, env);
  if (!clean || isSpecialBashPath(clean)) return false;
  if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(clean)) return false;
  if (clean.includes('/') || clean.includes('.')) return true;
  return BASH_KNOWN_FILES.has(clean) || BASH_KNOWN_FILES.has(path.basename(clean));
}

function isSpecialBashPath(target) {
  return BASH_SPECIAL_PATHS.has(target);
}

function attachedBashWriteRedirectTarget(token) {
  const text = String(token || '');
  const match = text.match(/^(?:[12]?>>?|&>>?)(.+)$/);
  return match ? match[1] : '';
}

function flagHasInlineValue(token) {
  return String(token || '').startsWith('--') && String(token).includes('=');
}

// --- Display helpers ---

function budgetInt(name, fallback, min, max) {
  const parsed = Number(process.env[name] || process.env[name.replace('AIDS_', 'AID_')] || fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(parsed)));
}

function formatAgo(ts) {
  let diffMs;
  try { diffMs = Date.now() - new Date(ts).getTime(); } catch { return '?'; }
  if (diffMs < 60000) return `${Math.floor(diffMs / 1000)}s ago`;
  if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
  return `${Math.floor(diffMs / 3600000)}h ago`;
}

function clip(value, charBudget) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= charBudget) return text;
  return text.slice(0, charBudget - 1).trimEnd() + '…';
}

function budgetLines(lines, lineBudget) {
  if (lines.length <= lineBudget) return lines;
  const hidden = lines.length - lineBudget + 1;
  return lines.slice(0, lineBudget - 1).concat(`  • ${hidden} context lines clipped; use aids trace/recent tools to expand.`);
}

module.exports = {
  inferRuntime,
  inferActorType,
  resolveAgentId,
  extractResourceKeys,
  extractBashResources,
  budgetInt,
  formatAgo,
  clip,
  budgetLines,
};
