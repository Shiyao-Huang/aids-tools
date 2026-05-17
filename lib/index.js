/**
 * AIDS (Agent-ID System) — Resource Index
 *
 * Maps file paths → array of trace IDs.
 * Storage: ~/.aids/index/{base64_path}.json
 *
 * Provides O(1) "who touched this file recently?" lookup.
 */

const fs = require('fs');
const path = require('path');
const { INDEX_DIR } = require('./constants');

function ensureDir() {
  if (!fs.existsSync(INDEX_DIR)) {
    fs.mkdirSync(INDEX_DIR, { recursive: true });
  }
}

function indexPath(filePath) {
  // Use URL-safe base64 of the file path as the index key
  const b64 = Buffer.from(filePath).toString('base64').replace(/\//g, '_').replace(/=/g, '');
  return path.join(INDEX_DIR, `${b64}.json`);
}

/**
 * Get recent trace IDs for a file.
 * @param {string} filePath
 * @param {number} limit
 * @returns {string[]} trace IDs
 */
function lastOps(filePath, limit = 5) {
  const fp = indexPath(filePath);
  if (!fs.existsSync(fp)) return [];
  const ids = JSON.parse(fs.readFileSync(fp, 'utf-8'));
  return ids.slice(-limit);
}

/**
 * Update index: append a trace ID for a file path.
 * @param {string} filePath
 * @param {string} traceId
 */
function update(filePath, traceId) {
  ensureDir();
  const fp = indexPath(filePath);
  let ids = [];
  if (fs.existsSync(fp)) {
    ids = JSON.parse(fs.readFileSync(fp, 'utf-8'));
  }
  ids.push(traceId);
  // Keep index bounded — last 100 entries per resource
  if (ids.length > 100) ids = ids.slice(-100);
  fs.writeFileSync(fp, JSON.stringify(ids), 'utf-8');
}

module.exports = { lastOps, update };
