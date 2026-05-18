#!/usr/bin/env python3
"""Additional unit tests for bin/selftools CLI commands.

Covers: export execution, register-session CLI, rate CLI, heartbeat,
whois, detect_resources, FileLock, date_range helper, retire-session.

Run: python3 -m unittest tests.test_selftools_extra -v
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
import types

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"

selftools = types.ModuleType("selftools")
selftools.__file__ = str(BIN_DIR / "selftools")
selftools.__name__ = "selftools"
sys.modules["selftools"] = selftools
with open(BIN_DIR / "selftools", "r", encoding="utf-8") as _f:
    exec(compile(_f.read(), BIN_DIR / "selftools", "exec"), selftools.__dict__)


class TempDataMixin:
    _SESSION_ENV_VARS = [
        "AIDS_SESSION_ID", "AID_SESSION_ID", "SESSION_ID",
        "SELFTOOLS_SESSION_ID", "ZHUYI_SESSION_ID", "AHA_SESSION_ID",
        "AIDS_RUNTIME", "AID_RUNTIME", "SELFTOOLS_RUNTIME", "ZHUYI_RUNTIME",
        "AIDS_ROLE", "AID_ROLE", "AHA_AGENT_ROLE", "ROLE",
        "SELFTOOLS_ROLE", "ZHUYI_ROLE", "AHA_ROLE",
        "AIDS_DISPLAY_NAME", "AID_DISPLAY_NAME",
        "SELFTOOLS_DISPLAY_NAME", "ZHUYI_DISPLAY_NAME", "AHA_SESSION_NAME",
        "AIDS_INTENT", "AID_INTENT", "INTENT",
        "SELFTOOLS_INTENT", "ZHUYI_INTENT", "AHA_INTENT", "AHA_AGENT_SCOPE_SUMMARY",
        "AIDS_TEAM_ID", "AID_TEAM_ID", "TEAM_ID",
        "SELFTOOLS_TEAM_ID", "ZHUYI_TEAM_ID", "AHA_TEAM_ID",
        "AIDS_TASK_ID", "AID_TASK_ID", "TASK_ID",
        "SELFTOOLS_TASK_ID", "ZHUYI_TASK_ID", "AHA_TASK_ID",
        "CLAUDE_ENV_FILE",
    ]

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aids_test_extra_")
        self._orig_data_dir = selftools.DEFAULT_DATA_DIR
        selftools.DEFAULT_DATA_DIR = Path(self._tmpdir)
        self._saved_env = {}
        for key in self._SESSION_ENV_VARS:
            if key in os.environ:
                self._saved_env[key] = os.environ.pop(key)

    def tearDown(self):
        selftools.DEFAULT_DATA_DIR = self._orig_data_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        os.environ.update(self._saved_env)
        for key in self._SESSION_ENV_VARS:
            if key not in self._saved_env and key in os.environ:
                del os.environ[key]


class TestCmdExport(TempDataMixin, unittest.TestCase):
    """Export tests use --session filter to isolate from real trace data."""

    def _seed_traces(self):
        today_file = selftools.traces_file_for_today()
        for i in range(3):
            selftools.append_jsonl(today_file, {
                "trace_id": f"tr_ex_{i}",
                "session_id": "s_ex_uniq",
                "tool": "Write",
                "resource_path": f"/tmp/export_{i}.py",
                "operation": "modify",
                "intent": "export test",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
                "runtime": "claude",
                "actor_type": "agent",
                "role": "implementer",
            })

    def test_export_jsonl(self):
        self._seed_traces()
        captured = io.StringIO()
        with patch("sys.stdout", captured), patch("sys.stderr"):
            args = type("A", (), {
                "data_dir": None, "format": "jsonl", "session": "s_ex_uniq",
                "resource": None, "output": None, "all": True,
                "from_date": None, "to_date": None, "days": 7,
            })()
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        lines = [l for l in captured.getvalue().strip().splitlines() if l.strip()]
        # metadata line + 3 record lines = 4
        self.assertEqual(len(lines), 4)
        self.assertIn("metadata", lines[0])

    def test_export_json(self):
        self._seed_traces()
        captured = io.StringIO()
        with patch("sys.stdout", captured), patch("sys.stderr"):
            args = type("A", (), {
                "data_dir": None, "format": "json", "session": "s_ex_uniq",
                "resource": None, "output": None, "all": True,
                "from_date": None, "to_date": None, "days": 7,
            })()
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        # JSON export wraps in {"metadata": ..., "data": {"traces": [...]}}
        self.assertIn("metadata", result)
        self.assertIn("data", result)
        traces = result["data"]["traces"]
        self.assertEqual(len(traces), 3)

    def test_export_csv(self):
        self._seed_traces()
        captured = io.StringIO()
        with patch("sys.stdout", captured), patch("sys.stderr"):
            args = type("A", (), {
                "data_dir": None, "format": "csv", "session": "s_ex_uniq",
                "resource": None, "output": None, "all": True,
                "from_date": None, "to_date": None, "days": 7,
                "type": "traces",
            })()
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        lines = captured.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 4)  # header + 3 rows
        self.assertIn("trace_id", lines[0])

    def test_export_to_file(self):
        self._seed_traces()
        outfile = Path(self._tmpdir) / "export.jsonl"
        args = type("A", (), {
            "data_dir": None, "format": "jsonl", "session": "s_ex_uniq",
            "resource": None, "output": str(outfile), "all": True,
            "from_date": None, "to_date": None, "days": 7,
        })()
        with patch("sys.stderr"):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        self.assertTrue(outfile.exists())
        lines = outfile.read_text().strip().splitlines()
        # metadata line + 3 record lines = 4
        self.assertEqual(len(lines), 4)


class TestCmdRegisterSession(TempDataMixin, unittest.TestCase):
    def test_register_via_cli(self):
        args = selftools.build_parser().parse_args([
            "register-session", "--session-id", "cli-reg-1",
            "--runtime", "claude", "--role", "tester",
            "--goal", "test registration", "--display-name", "TestBot",
        ])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_register_session(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["session_id"], "cli-reg-1")
        self.assertEqual(result["status"], "active")
        loaded = selftools.load_session("cli-reg-1")
        self.assertEqual(loaded["session_id"], "cli-reg-1")


class TestCmdRate(TempDataMixin, unittest.TestCase):
    def test_rate_existing_trace(self):
        trace = {
            "trace_id": "tr_rate_cli",
            "session_id": "s1",
            "tool": "Write",
            "resource_path": "/tmp/rate_cli.py",
            "operation": "modify",
            "intent": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)

        args = selftools.build_parser().parse_args(["rate", "tr_rate_cli", "good", "nice work"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_rate(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["score"], "good")
        self.assertEqual(result["comment"], "nice work")

    def test_rate_nonexistent_trace(self):
        args = selftools.build_parser().parse_args(["rate", "tr_ghost", "bad", "missing"])
        rc = selftools.cmd_rate(args)
        self.assertEqual(rc, 1)


class TestCmdHeartbeat(TempDataMixin, unittest.TestCase):
    def test_heartbeat_updates_last_seen(self):
        record = {
            "session_id": "hb-1",
            "status": "active",
            "started_at": selftools.now_ms() - 60000,
            "started_iso": selftools.iso_now(),
        }
        selftools.write_json_atomic(selftools.session_path("hb-1"), record)

        args = selftools.build_parser().parse_args(["heartbeat", "hb-1", "--json"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_heartbeat(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertGreater(result["last_seen_at"], 0)

    def test_heartbeat_missing_session(self):
        args = selftools.build_parser().parse_args(["heartbeat", "ghost-session"])
        rc = selftools.cmd_heartbeat(args)
        self.assertEqual(rc, 1)


class TestCmdWhois(TempDataMixin, unittest.TestCase):
    def test_whois_existing(self):
        record = {
            "session_id": "whois-1",
            "role": "implementer",
            "runtime": "claude",
            "display_name": "TestAgent",
            "goal": "testing",
            "started_at": selftools.now_ms() - 300000,
            "started_iso": selftools.iso_now(),
            "last_seen_at": selftools.now_ms(),
            "last_seen_iso": selftools.iso_now(),
            "status": "active",
        }
        selftools.write_json_atomic(selftools.session_path("whois-1"), record)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            args = selftools.build_parser().parse_args(["whois", "whois-1"])
            rc = selftools.cmd_whois(args)
        self.assertEqual(rc, 0)
        self.assertIn("whois-1", captured.getvalue())

    def test_whois_json(self):
        record = {"session_id": "whois-2", "role": "qa", "status": "active"}
        selftools.write_json_atomic(selftools.session_path("whois-2"), record)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            args = selftools.build_parser().parse_args(["whois", "whois-2", "--json"])
            rc = selftools.cmd_whois(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["session_id"], "whois-2")


class TestDetectResources(unittest.TestCase):
    def test_read_file(self):
        result = selftools.detect_resources("Read", {"file_path": "/tmp/a.py"}, "/tmp")
        self.assertTrue(any("a.py" in r for r in result))

    def test_bash_command(self):
        result = selftools.detect_resources("Bash", {"command": "ls -la"}, "/tmp")
        self.assertTrue(any(r.startswith("bash:") for r in result))

    def test_bash_redirection_target(self):
        result = selftools.detect_resources("Bash", {"command": "printf hi > out.txt"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/out.txt") for r in result))

    def test_bash_redirect_stderr(self):
        result = selftools.detect_resources("Bash", {"command": "cmd 2> err.log"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/err.log") for r in result))

    def test_bash_redirect_stderr_append(self):
        result = selftools.detect_resources("Bash", {"command": "cmd 2>> err.log"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/err.log") for r in result))

    def test_bash_redirect_all(self):
        result = selftools.detect_resources("Bash", {"command": "cmd &> all.log"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/all.log") for r in result))

    def test_bash_redirect_all_append(self):
        result = selftools.detect_resources("Bash", {"command": "cmd &>> all.log"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/all.log") for r in result))

    def test_bash_attached_redirect(self):
        result = selftools.detect_resources("Bash", {"command": "echo hi >out.txt"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/out.txt") for r in result))

    def test_bash_attached_stderr_redirect(self):
        result = selftools.detect_resources("Bash", {"command": "cmd 2>err.log"}, "/tmp")
        self.assertTrue(any(r.endswith("/tmp/err.log") for r in result))

    def test_bash_multiple_redirects(self):
        result = selftools.detect_resources("Bash", {"command": "cmd > out.txt 2> err.log"}, "/tmp")
        paths = [r for r in result if not r.startswith("bash:")]
        self.assertEqual(len(paths), 2)

    def test_tee_multiple_targets(self):
        result = selftools.detect_resources("Bash", {"command": "cat file | tee a.txt b.txt c.txt"}, "/tmp")
        paths = [r for r in result if not r.startswith("bash:")]
        basenames = [os.path.basename(p) for p in paths]
        self.assertIn("a.txt", basenames)
        self.assertIn("b.txt", basenames)
        self.assertIn("c.txt", basenames)

    def test_tee_single_target(self):
        result = selftools.detect_resources("Bash", {"command": "echo hi | tee out.txt"}, "/tmp")
        paths = [r for r in result if not r.startswith("bash:")]
        self.assertTrue(any(p.endswith("/tmp/out.txt") for p in paths))

    def test_redirect_dev_null_filtered(self):
        result = selftools.detect_resources("Bash", {"command": "cmd 2>/dev/null"}, "/tmp")
        paths = [r for r in result if not r.startswith("bash:")]
        self.assertNotIn("/dev/null", paths)
        self.assertEqual(len(paths), 0)

    def test_mcp_tool(self):
        result = selftools.detect_resources("mcp__pencil_batch_design", {"filePath": "test.pen"}, "/tmp")
        self.assertTrue(any(r.startswith("mcp:") for r in result))

    def test_non_dict_input(self):
        result = selftools.detect_resources("Read", "not a dict", "/tmp")
        self.assertEqual(result, [])

    def test_empty_file_path(self):
        result = selftools.detect_resources("Read", {"file_path": ""}, "/tmp")
        self.assertEqual(result, [])


class TestFileLock(TempDataMixin, unittest.TestCase):
    def test_basic_lock_unlock(self):
        lock_file = Path(self._tmpdir) / "locks" / "test.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with selftools.FileLock(lock_file, timeout=2.0):
            self.assertTrue(lock_file.exists())

    def test_stale_lock_cleaned(self):
        lock_file = Path(self._tmpdir) / "locks" / "stale.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        stale_info = {"pid": 99999999, "timestamp": (time.time() - 600) * 1000}
        lock_file.write_text(json.dumps(stale_info), encoding="utf-8")
        with selftools.FileLock(lock_file, timeout=2.0) as lock:
            self.assertTrue(lock._owns_lock)


class TestDateRangeHelper(unittest.TestCase):
    def test_all_flag(self):
        args = type("A", (), {"all": True, "from_date": None, "to_date": None, "days": 7})()
        frm, to = selftools._date_range(args)
        self.assertIsNone(frm)
        self.assertIsNone(to)

    def test_explicit_dates(self):
        args = type("A", (), {"all": False, "from_date": "2026-01-01", "to_date": "2026-01-31", "days": 7})()
        frm, to = selftools._date_range(args)
        self.assertEqual(frm, "2026-01-01")
        self.assertEqual(to, "2026-01-31")

    def test_default_days(self):
        args = type("A", (), {"all": False, "from_date": None, "to_date": None, "days": 3})()
        frm, to = selftools._date_range(args)
        self.assertIsNotNone(frm)
        self.assertIsNotNone(to)


class TestCmdRetireSession(TempDataMixin, unittest.TestCase):
    def test_retire_existing(self):
        record = {
            "session_id": "retire-1",
            "status": "active",
            "started_at": selftools.now_ms(),
            "started_iso": selftools.iso_now(),
        }
        selftools.write_json_atomic(selftools.session_path("retire-1"), record)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            args = selftools.build_parser().parse_args(["retire-session", "retire-1", "--reason", "done"])
            rc = selftools.cmd_retire_session(args)
        self.assertEqual(rc, 0)
        loaded = selftools.load_session("retire-1")
        self.assertEqual(loaded["status"], "retired")


class TestBashReadResources(unittest.TestCase):
    """Tests for parse_bash_read_resources — Bash read-operation detection."""

    def test_cat_detects_file(self):
        result = selftools.parse_bash_read_resources("cat /tmp/readme.md", "/tmp")
        self.assertTrue(any("readme.md" in r for r in result))

    def test_grep_detects_file(self):
        result = selftools.parse_bash_read_resources("grep pattern /tmp/app.py", "/tmp")
        self.assertTrue(any("app.py" in r for r in result))

    def test_head_detects_file(self):
        result = selftools.parse_bash_read_resources("head -n 10 /tmp/log.txt", "/tmp")
        self.assertTrue(any("log.txt" in r for r in result))

    def test_tail_detects_file(self):
        result = selftools.parse_bash_read_resources("tail -f /tmp/debug.log", "/tmp")
        self.assertTrue(any("debug.log" in r for r in result))

    def test_sed_detects_file(self):
        result = selftools.parse_bash_read_resources("sed -n '1,5p' /tmp/data.txt", "/tmp")
        self.assertTrue(any("data.txt" in r for r in result))

    def test_awk_detects_file(self):
        result = selftools.parse_bash_read_resources("awk '{print $1}' /tmp/data.csv", "/tmp")
        self.assertTrue(any("data.csv" in r for r in result))

    def test_pipeline_stops_at_pipe(self):
        # cat reads the file; the pipe target is NOT a read target for wc
        result = selftools.parse_bash_read_resources("cat /tmp/input.txt | wc -l", "/tmp")
        self.assertTrue(any("input.txt" in r for r in result))
        # wc runs after pipe — its args shouldn't appear
        self.assertFalse(any("wc" in r for r in result))

    def test_flags_skipped(self):
        result = selftools.parse_bash_read_resources("grep -r -i pattern /tmp/src", "/tmp")
        self.assertTrue(any("src" in r for r in result))

    def test_dev_null_filtered(self):
        result = selftools.parse_bash_read_resources("cat /dev/null", "/tmp")
        self.assertEqual(len(result), 0)

    def test_no_file_args(self):
        result = selftools.parse_bash_read_resources("cat", "/tmp")
        self.assertEqual(len(result), 0)

    def test_non_path_args_skipped(self):
        # bare words without / or . are not file paths
        result = selftools.parse_bash_read_resources("grep pattern", "/tmp")
        self.assertEqual(len(result), 0)

    def test_detect_resources_integrates_reads(self):
        resources = selftools.detect_resources("Bash", {"command": "cat /tmp/a.txt"}, "/tmp")
        # Should contain bash:resource AND the read target
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertTrue(any("a.txt" in p for p in paths))

    def test_diff_detects_files(self):
        result = selftools.parse_bash_read_resources("diff /tmp/a.txt /tmp/b.txt", "/tmp")
        self.assertEqual(len(result), 2)


class TestWhoTouchedSort(TempDataMixin, unittest.TestCase):
    """Tests for who-touched --sort and --reverse flags."""

    def _seed_traces(self, resource):
        """Seed two traces with different operations and agents."""
        for i, (op, tool, name) in enumerate([
            ("modify", "Edit", "Alice"),
            ("read", "Read", "Bob"),
            ("create", "Write", "Alice"),
        ]):
            session = {"session_id": f"s_sort{i}", "runtime": "claude", "role": "implementer",
                       "display_name": name, "status": "active", "agent_id": f"aid_{name}"}
            selftools.write_json_atomic(selftools.session_path(f"s_sort{i}"), session)
            trace = {
                "trace_id": f"tr_sort{i}", "session_id": f"s_sort{i}", "tool": tool,
                "resource_path": resource, "operation": op, "intent": "test",
                "timestamp": selftools.now_ms() + i * 1000, "timestamp_iso": selftools.iso_now(),
                "runtime": "claude", "actor_type": "agent", "role": "implementer",
                "agent_id": f"aid_{name}",
            }
            selftools.append_jsonl(selftools.traces_file_for_today(), trace)
            selftools.update_index(resource, trace, session)

    def test_sort_by_operation(self):
        resource = str(Path("/tmp/sort_test.py").resolve())
        self._seed_traces(resource)
        args = selftools.build_parser().parse_args(["who-touched", resource, "--sort", "operation"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 0)
        output = captured.getvalue()
        # "create" comes before "modify" alphabetically, which comes before "read"
        pos_create = output.find("create")
        pos_modify = output.find("modify")
        pos_read = output.find("read")
        self.assertGreater(pos_create, -1)
        self.assertGreater(pos_modify, -1)
        self.assertGreater(pos_read, -1)
        self.assertLess(pos_create, pos_modify)
        self.assertLess(pos_modify, pos_read)

    def test_sort_by_agent(self):
        resource = str(Path("/tmp/sort_agent.py").resolve())
        self._seed_traces(resource)
        args = selftools.build_parser().parse_args(["who-touched", resource, "--sort", "agent"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 0)
        output = captured.getvalue()
        # Alice traces should appear before Bob traces
        pos_alice = output.find("Alice")
        pos_bob = output.find("Bob")
        self.assertGreater(pos_alice, -1)
        self.assertGreater(pos_bob, -1)
        self.assertLess(pos_alice, pos_bob)

    def test_reverse_flag(self):
        resource = str(Path("/tmp/sort_rev.py").resolve())
        self._seed_traces(resource)
        args = selftools.build_parser().parse_args(["who-touched", resource, "--reverse"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 0)

    def test_default_sort_is_time(self):
        resource = str(Path("/tmp/sort_time.py").resolve())
        self._seed_traces(resource)
        args = selftools.build_parser().parse_args(["who-touched", resource])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 0)


class TestColorHelpers(unittest.TestCase):
    """Tests for ANSI color helpers — NO_COLOR and non-tty behavior."""

    def test_no_color_env_disables(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            # Re-import the check by calling the helper directly
            import importlib
            # The module is exec'd; just test the function
            original_no_color = selftools._NO_COLOR
            selftools._NO_COLOR = True
            result = selftools._color("36", "hello")
            self.assertEqual(result, "hello")
            selftools._NO_COLOR = original_no_color

    def test_color_returns_plain_when_not_tty(self):
        import io as _io
        buf = _io.StringIO()
        with patch("sys.stdout", buf):
            # isatty() returns False for StringIO
            result = selftools._color("36", "hello")
            self.assertEqual(result, "hello")

    def test_bold_and_dim(self):
        # Just ensure they don't crash
        selftools._NO_COLOR = False
        with patch("sys.stdout.isatty", return_value=True):
            b = selftools._bold("test")
            d = selftools._dim("test")
            # Should contain ANSI codes
            self.assertIn("\033[", b)
            self.assertIn("\033[", d)
        selftools._NO_COLOR = True  # reset


class TestAppendJsonlMulti(TempDataMixin, unittest.TestCase):
    """Test append_jsonl_multi batch write function."""

    def test_multi_writes_all_records(self):
        path = selftools.traces_file_for_today()
        records = [
            {"trace_id": f"tr_batch_{i}", "session_id": "s_batch", "tool": "Write"}
            for i in range(5)
        ]
        selftools.append_jsonl_multi(path, records)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 5)
        for i, line in enumerate(lines):
            obj = json.loads(line)
            self.assertEqual(obj["trace_id"], f"tr_batch_{i}")

    def test_multi_empty_list_is_noop(self):
        path = selftools.traces_file_for_today()
        selftools.append_jsonl_multi(path, [])
        self.assertFalse(path.exists())

    def test_multi_reduces_lock_acquisitions(self):
        """Verify batch write produces same result as sequential writes."""
        path1 = Path(self._tmpdir) / "batch.jsonl"
        path2 = Path(self._tmpdir) / "seq.jsonl"
        records = [{"id": i, "data": f"record_{i}"} for i in range(10)]
        selftools.append_jsonl_multi(path1, records)
        for r in records:
            selftools.append_jsonl(path2, r)
        self.assertEqual(
            path1.read_text(encoding="utf-8"),
            path2.read_text(encoding="utf-8"),
        )


class TestProtectedConfigKeys(TempDataMixin, unittest.TestCase):
    """Test that protected config keys cannot be overridden by user config."""

    def test_protected_signature_enabled(self):
        """User cannot disable signature via config.json."""
        config_path = selftools.data_dir() / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "signature": {"enabled": False, "strategy": "bad_value"},
        }), encoding="utf-8")
        with patch.object(selftools, "data_dir", return_value=selftools.DEFAULT_DATA_DIR):
            config = selftools.load_aids_config()
        self.assertTrue(config["signature"]["enabled"])
        self.assertEqual(config["signature"]["strategy"], "hash_chain")

    def test_protected_impact_enabled(self):
        """User cannot disable impact via config.json."""
        config_path = selftools.DEFAULT_DATA_DIR / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "impact": {"enabled": False},
        }), encoding="utf-8")
        config = selftools.load_aids_config()
        self.assertTrue(config["impact"]["enabled"])

    def test_non_protected_keys_override(self):
        """Non-protected keys can still be overridden."""
        config_path = selftools.DEFAULT_DATA_DIR / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "query": {"default_limit": 20},
            "output": {"max_chars": 500},
        }), encoding="utf-8")
        config = selftools.load_aids_config()
        self.assertEqual(config["query"]["default_limit"], 20)
        self.assertEqual(config["output"]["max_chars"], 500)

    def test_deep_merge_skips_protected(self):
        """_deep_merge_dict skips protected keys during merge."""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"x": 99, "y": 88}, "b": 99}
        # Temporarily override PROTECTED_CONFIG_KEYS to test merge logic
        original = selftools.PROTECTED_CONFIG_KEYS
        selftools.PROTECTED_CONFIG_KEYS = {"a.x": True}
        try:
            merged = selftools._deep_merge_dict(base, override)
            self.assertEqual(merged["a"]["x"], 1)  # protected, not overridden
            self.assertEqual(merged["a"]["y"], 88)  # not protected, overridden
            self.assertEqual(merged["b"], 99)  # not protected, overridden
        finally:
            selftools.PROTECTED_CONFIG_KEYS = original


if __name__ == "__main__":
    unittest.main()
