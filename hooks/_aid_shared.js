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
  const hash = crypto.createHash('sha256').update(command).digest('hex').slice(0, 16);
  results.push(`bash:${hash}`);

  // Detect file-mutation targets: > >> tee mv cp
  const patterns = [
    />\s*["']?([^"'\s;|&]+)/g,
    />>\s*["']?([^"'\s;|&]+)/g,
    /tee\s+["']?([^"'\s;|&]+)/g,
    /\b(?:mv|cp)\s+["']?[^"'\s]+["']?\s+["']?([^"'\s;|&]+)/g,
  ];
  for (const pat of patterns) {
    let m;
    while ((m = pat.exec(command)) !== null) {
      const target = m[1] || m[m.length - 1];
      if (target && !target.startsWith('-')) {
        try { results.push(normalizeFilePath(target)); } catch { /* skip */ }
      }
    }
  }

  // Detect read-only file targets: cat grep head tail wc sort uniq sed(without -i) etc.
  const readCmds = new Set([
    'cat', 'head', 'tail', 'less', 'more', 'wc', 'sort', 'uniq',
    'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack',
    'sed', 'awk', 'diff', 'comm', 'cut', 'tr',
    'file', 'stat', 'md5sum', 'sha256sum', 'sha1sum', 'shasum',
    'strings', 'hexdump', 'xxd', 'od',
  ]);
  const valueFlags = new Set([
    '-e', '--regexp', '-f', '--file', '-n', '--lines', '-c', '--bytes',
    '-k', '--key', '-t', '--field-separator', '-o', '--output',
    '-F', '-v', '-d', '--delimiter', '--label', '-L', '-U', '--unified',
    '-i', '--in-place',
  ]);
  const specialPaths = new Set(['/dev/null', '/dev/zero', '/dev/random', '/dev/urandom', '-']);
  const knownFiles = new Set([
    'Makefile', 'Dockerfile', 'README', 'LICENSE', 'CHANGELOG',
    'Rakefile', 'Gemfile', 'Vagrantfile', 'Jenkinsfile',
  ]);

  for (const segment of command.split('|')) {
    const tokens = segment.trim().split(/\s+/);
    if (!tokens.length) continue;
    const base = path.basename(tokens[0]);
    if (!readCmds.has(base)) continue;
    if (base === 'sed' && tokens.some(t => t === '-i' || /^-[^e]*i/.test(t))) continue;
    let skip = false;
    for (const tok of tokens.slice(1)) {
      if (skip) { skip = false; continue; }
      if (tok === ';' || tok === '&&' || tok === '||') break;
      if (valueFlags.has(tok)) { skip = true; continue; }
      if (tok.startsWith('-')) continue;
      if (specialPaths.has(tok)) continue;
      if (tok.includes('/') || tok.includes('.') || knownFiles.has(tok)) {
        try { results.push(normalizeFilePath(tok)); } catch { /* skip */ }
      }
    }
  }

  return results;
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
