#!/usr/bin/env node
/**
 * Session Registry — identity store and lookup API
 *
 * Manages session identity store at ~/.aids/registry.json
 * Thread-safe via write-then-rename pattern.
 *
 * Schema: { sessionId, role, agentName, purpose, startedAt, lastSeenAt, isActive }
 *
 * CLI: node src/registry/registry.js register|lookup|list|deactivate
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

// ── Config ──────────────────────────────────────────────────────────

function firstEnv(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

const BASE_DIR = path.resolve(
  expandHome(
    firstEnv(
      "AIDS_HOME",
      "AIDS_DATA_DIR",
      "AID_HOME",
      "AID_DATA_DIR",
      "SELFTOOLS_DATA_DIR",
      "SELFTOOLS_HOME",
      "CONSCIOUS_TOOLS_HOME",
      "ZHUYI_DATA_DIR",
      "ZHUYI_HOME",
    ) || path.join(os.homedir(), ".aids"),
  ),
);
const REGISTRY_PATH = path.join(BASE_DIR, "registry.json");

function expandHome(value) {
  if (!value || value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

// ── Thread-safe file I/O ────────────────────────────────────────────

/**
 * Write-then-rename: write to a temp file, then atomically rename.
 * Safe against concurrent writers and crash mid-write.
 */
function atomicWriteJSON(filePath, data) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });

  const tmp = path.join(
    dir,
    `.registry_${crypto.randomBytes(8).toString("hex")}.tmp`
  );

  try {
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + "\n", "utf8");
    fs.renameSync(tmp, filePath);
  } catch (err) {
    // Clean up temp file on failure
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    throw err;
  }
}

/**
 * Read the registry file. Returns { sessions: {} } if missing or corrupt.
 */
function readRegistry() {
  try {
    const raw = fs.readFileSync(REGISTRY_PATH, "utf8");
    return JSON.parse(raw);
  } catch {
    return { sessions: {} };
  }
}

// ── Core API ────────────────────────────────────────────────────────

/**
 * Register or update a session.
 * @param {string} sessionId - Unique session identifier
 * @param {string} role - Agent role (architect, builder, scribe, etc.)
 * @param {string} name - Human-readable agent name
 * @param {string} purpose - Declared intent for this session
 * @returns {object} The session record
 */
function registerSession(sessionId, role, name, purpose) {
  if (!sessionId) throw new Error("sessionId is required");

  const registry = readRegistry();
  const now = Date.now();
  const existing = registry.sessions[sessionId];

  const record = {
    sessionId,
    role: role || "unknown",
    agentName: name || "unnamed",
    purpose: purpose || "",
    startedAt: existing ? existing.startedAt : now,
    lastSeenAt: now,
    isActive: true,
  };

  registry.sessions[sessionId] = record;
  atomicWriteJSON(REGISTRY_PATH, registry);
  return record;
}

/**
 * Look up a session by ID.
 * @param {string} sessionId
 * @returns {object|null} Session record or null
 */
function lookupSession(sessionId) {
  if (!sessionId) throw new Error("sessionId is required");
  const registry = readRegistry();
  return registry.sessions[sessionId] || null;
}

/**
 * List all active sessions.
 * @returns {object[]} Array of active session records
 */
function listActiveSessions() {
  const registry = readRegistry();
  return Object.values(registry.sessions).filter((s) => s.isActive);
}

/**
 * Deactivate a session (soft delete).
 * @param {string} sessionId
 * @returns {object|null} Updated record or null if not found
 */
function deactivateSession(sessionId) {
  if (!sessionId) throw new Error("sessionId is required");
  const registry = readRegistry();
  const record = registry.sessions[sessionId];

  if (!record) return null;

  record.isActive = false;
  record.lastSeenAt = Date.now();
  atomicWriteJSON(REGISTRY_PATH, registry);
  return record;
}

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Resolve SESSION_ID from env var or ~/.aids/session.env
 */
function resolveSessionId() {
  const fromEnv = firstEnv("AIDS_SESSION_ID", "AID_SESSION_ID", "SESSION_ID", "SELFTOOLS_SESSION_ID", "ZHUYI_SESSION_ID", "AHA_SESSION_ID");
  if (fromEnv) return fromEnv;

  const envPath = path.join(BASE_DIR, "session.env");
  try {
    const lines = fs.readFileSync(envPath, "utf8").split("\n");
    for (const line of lines) {
      const match = line.match(/^(?:AIDS_SESSION_ID|AID_SESSION_ID|SESSION_ID|SELFTOOLS_SESSION_ID|ZHUYI_SESSION_ID)=(.+)$/);
      if (match) return match[1].trim().replace(/^["']|["']$/g, "");
    }
  } catch { /* file doesn't exist */ }

  return null;
}

// ── CLI ─────────────────────────────────────────────────────────────

function printUsage() {
  console.log(`Usage: node src/registry/registry.js <command> [args]

Commands:
  register <role> <name> <purpose>   Register current session
  register <sessionId> <role> <name> <purpose>  Register specific session
  lookup <sessionId>                 Look up a session by ID
  list                               List all active sessions
  deactivate <sessionId>             Deactivate a session

Environment:
  AIDS_SESSION_ID  Session ID (or read from ~/.aids/session.env)
  Legacy aliases: AID_SESSION_ID, SESSION_ID, SELFTOOLS_SESSION_ID, ZHUYI_SESSION_ID`);
}

function cliMain() {
  const args = process.argv.slice(2);
  const command = args[0];

  try {
    switch (command) {
      case "register": {
        let sessionId, role, name, purpose;
        const params = args.slice(1);

        if (params.length === 4) {
          // register <sessionId> <role> <name> <purpose>
          [sessionId, role, name, purpose] = params;
        } else if (params.length === 3) {
          // register <role> <name> <purpose> — uses env session ID
          sessionId = resolveSessionId();
          if (!sessionId) {
            console.error("Error: No session ID. Set AIDS_SESSION_ID or pass as first arg.");
            process.exit(1);
          }
          [role, name, purpose] = params;
        } else {
          console.error("Usage: register <role> <name> <purpose>");
          console.error("   or: register <sessionId> <role> <name> <purpose>");
          process.exit(1);
        }

        const record = registerSession(sessionId, role, name, purpose);
        console.log(JSON.stringify(record, null, 2));
        break;
      }

      case "lookup": {
        const sessionId = args[1];
        if (!sessionId) {
          console.error("Usage: lookup <sessionId>");
          process.exit(1);
        }
        const record = lookupSession(sessionId);
        if (record) {
          console.log(JSON.stringify(record, null, 2));
        } else {
          console.log("Session not found.");
          process.exit(1);
        }
        break;
      }

      case "list": {
        const sessions = listActiveSessions();
        if (sessions.length === 0) {
          console.log("No active sessions.");
        } else {
          for (const s of sessions) {
            console.log(
              `${s.sessionId}  ${s.role.padEnd(12)} ${s.agentName.padEnd(24)} ${s.purpose}`
            );
          }
        }
        break;
      }

      case "deactivate": {
        const sessionId = args[1];
        if (!sessionId) {
          console.error("Usage: deactivate <sessionId>");
          process.exit(1);
        }
        const record = deactivateSession(sessionId);
        if (record) {
          console.log(`Deactivated: ${record.sessionId} (${record.agentName})`);
        } else {
          console.log("Session not found.");
          process.exit(1);
        }
        break;
      }

      default:
        printUsage();
        process.exit(command ? 1 : 0);
    }
  } catch (err) {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  }
}

// Export for programmatic use; run CLI when executed directly
module.exports = { registerSession, lookupSession, listActiveSessions, deactivateSession, resolveSessionId };

if (require.main === module) {
  cliMain();
}
