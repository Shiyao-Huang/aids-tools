#!/usr/bin/env python3
"""Hook output contract checks for Codex/Claude compatibility."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELFTOOLS = ROOT / "bin" / "selftools"


class TestHookOutputContract(unittest.TestCase):
    def test_post_tool_use_omits_top_level_additional_context(self) -> None:
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "printf hi"},
            "tool_result": {"output": "hi"},
            "cwd": str(ROOT),
            "session_id": "contract-test-session",
        }
        with tempfile.TemporaryDirectory(prefix="aids-hook-contract-") as tmp:
            env = os.environ.copy()
            env.update(
                {
                    "AIDS_DATA_DIR": tmp,
                    "AIDS_HOME": tmp,
                    "AIDS_RUNTIME": "codex",
                    "AIDS_SESSION_ID": "contract-test-session",
                }
            )
            proc = subprocess.run(
                [sys.executable, str(SELFTOOLS), "hook", "post-tool-use"],
                input=json.dumps(event),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertNotIn("additionalContext", payload)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("additionalContext", payload["hookSpecificOutput"])


if __name__ == "__main__":
    unittest.main()
