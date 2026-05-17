/**
 * AIDS (Agent-ID System) — shared constants.
 *
 * Primary public surface:
 *   - env: AIDS_*
 *   - data home: ~/.aids
 *
 * Legacy aliases are still accepted during migration:
 *   AID_*, SELFTOOLS_*, ZHUYI_*, ~/.aid, ~/.zhuyi.
 */

const os = require('os');
const path = require('path');

function firstEnv(...names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

// Priority: AIDS_* > AID_* > SELFTOOLS_* > ZHUYI_* > default ~/.aids.
const AIDS_HOME = firstEnv(
  'AIDS_HOME',
  'AIDS_DATA_DIR',
  'AID_HOME',
  'AID_DATA_DIR',
  'SELFTOOLS_DATA_DIR',
  'SELFTOOLS_HOME',
  'CONSCIOUS_TOOLS_HOME',
  'ZHUYI_DATA_DIR',
  'ZHUYI_HOME',
) || path.join(os.homedir(), '.aids');

module.exports = {
  AIDS_HOME,
  // Backward-compatible export for old modules.
  ZHUYI_HOME: AIDS_HOME,
  SESSIONS_DIR: path.join(AIDS_HOME, 'sessions'),
  TRACES_DIR: path.join(AIDS_HOME, 'traces'),
  INDEX_DIR: path.join(AIDS_HOME, 'index'),
  RATINGS_DIR: path.join(AIDS_HOME, 'ratings'),
  CONFIG_PATH: path.join(AIDS_HOME, 'config.json'),

  // Environment variable names (primary AIDS_*, legacy aliases)
  ENV_SESSION_ID: 'AIDS_SESSION_ID',
  ENV_INTENT: 'AIDS_INTENT',
  ENV_ROLE: 'AIDS_ROLE',
  ENV_TASK_ID: 'AIDS_TASK_ID',

  // Tools that mutate state (require read-before-write check)
  WRITE_TOOLS: new Set(['Write', 'Edit']),
  // Tools that produce traces
  TRACED_TOOLS: new Set(['Write', 'Read', 'Edit', 'Bash']),

  // How many recent ops to surface in pre-tool-use injection
  RECENT_OPS_LIMIT: 5,
};
