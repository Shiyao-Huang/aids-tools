#!/usr/bin/env python3
"""Unit tests for bin/selftools Python CLI core logic.

Run: python -m pytest tests/test_selftools.py -v
     python -m unittest tests.test_selftools -v
"""
from __future__ import annotations

import datetime as _dt
import csv
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import the module under test
import sys

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"

import types

selftools = types.ModuleType("selftools")
selftools.__file__ = str(BIN_DIR / "selftools")
selftools.__name__ = "selftools"
sys.modules["selftools"] = selftools
with open(BIN_DIR / "selftools", "r", encoding="utf-8") as _f:
    exec(compile(_f.read(), BIN_DIR / "selftools", "exec"), selftools.__dict__)


class TempDataMixin:
    """Mixin that sets up a temporary AIDS_DATA_DIR for each test."""

    # Env vars that register_session / session_id_from read — save/restore.
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
        self._tmpdir = tempfile.mkdtemp(prefix="aids_test_")
        self._orig_data_dir = selftools.DEFAULT_DATA_DIR
        selftools.DEFAULT_DATA_DIR = Path(self._tmpdir)
        # Save and clear AIDS env vars so tests are isolated
        self._saved_env = {}
        for key in self._SESSION_ENV_VARS:
            if key in os.environ:
                self._saved_env[key] = os.environ.pop(key)

    def tearDown(self):
        selftools.DEFAULT_DATA_DIR = self._orig_data_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        # Restore env vars
        os.environ.update(self._saved_env)
        for key in self._SESSION_ENV_VARS:
            if key not in self._saved_env and key in os.environ:
                del os.environ[key]


# ─── Helper functions ───


class TestNormalizeResource(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(selftools.normalize_resource(""), "unknown")

    def test_absolute_path(self):
        result = selftools.normalize_resource("/tmp/foo.py")
        # macOS resolves /tmp -> /private/tmp
        self.assertTrue(result.endswith("foo.py"))
        self.assertTrue(result.startswith(("/tmp/", "/private/tmp/")))

    def test_relative_resolves(self):
        result = selftools.normalize_resource("foo.py", cwd="/tmp")
        self.assertTrue(result.endswith("foo.py"))

    def test_bash_prefix(self):
        self.assertEqual(selftools.normalize_resource("bash:git status"), "bash:git status")

    def test_mcp_prefix(self):
        # mcp__ does NOT start with "mcp:" — it's treated as a relative path
        result = selftools.normalize_resource("mcp__foo")
        self.assertIn("mcp__foo", result)

    def test_uri_scheme(self):
        self.assertEqual(selftools.normalize_resource("https://example.com"), "https://example.com")


class TestOperationFor(unittest.TestCase):
    def test_read(self):
        self.assertEqual(selftools.operation_for("Read", "/x", "h1", "h1"), "read")

    def test_bash(self):
        self.assertEqual(selftools.operation_for("Bash", "bash:ls", None, None), "execute")

    def test_create(self):
        self.assertEqual(selftools.operation_for("Write", "/x", None, "h2"), "create")

    def test_delete(self):
        self.assertEqual(selftools.operation_for("Write", "/x", "h1", None), "delete")

    def test_modify(self):
        self.assertEqual(selftools.operation_for("Write", "/x", "h1", "h2"), "modify")

    def test_touch(self):
        self.assertEqual(selftools.operation_for("Write", "/x", "h1", "h1"), "touch")


class TestShort(unittest.TestCase):
    def test_short_string(self):
        self.assertEqual(selftools.short("hello", 10), "hello")

    def test_truncation(self):
        result = selftools.short("a" * 200, 100)
        self.assertLessEqual(len(result), 100)
        self.assertTrue(result.endswith("…"))

    def test_none(self):
        self.assertEqual(selftools.short(None), "")


class TestIndexKey(unittest.TestCase):
    def test_deterministic(self):
        k1 = selftools.index_key("/tmp/foo.py")
        k2 = selftools.index_key("/tmp/foo.py")
        self.assertEqual(k1, k2)

    def test_different_paths(self):
        k1 = selftools.index_key("/tmp/foo.py")
        k2 = selftools.index_key("/tmp/bar.py")
        self.assertNotEqual(k1, k2)

    def test_long_resource_uses_short_hash_key(self):
        key = selftools.index_key("bash:" + ("echo " * 200))
        self.assertLess(len(key), 80)
        self.assertTrue(key.startswith("sha256-"))

    def test_bash_resource_stores_full_command(self):
        """detect_resources() must preserve the full bash command in resource_path."""
        long_cmd = "echo " + "x" * 500
        resources = selftools.detect_resources("Bash", {"command": long_cmd}, "/tmp")
        bash_res = [r for r in resources if r.startswith("bash:")]
        self.assertEqual(len(bash_res), 1)
        # Full command is preserved — not truncated
        self.assertIn("x" * 500, bash_res[0])

    def test_bash_redirect_creates_file_resource(self):
        """Bash echo > file creates both bash: and file resources."""
        resources = selftools.detect_resources(
            "Bash", {"command": "echo hello > /tmp/out.txt"}, "/tmp"
        )
        self.assertTrue(any(r.startswith("bash:") for r in resources))
        self.assertTrue(any("out.txt" in r for r in resources))

    def test_bash_tee_creates_file_resource(self):
        resources = selftools.detect_resources(
            "Bash", {"command": "echo data | tee /tmp/log.txt"}, "/tmp"
        )
        self.assertTrue(any("log.txt" in r for r in resources))


class TestDisplayResource(unittest.TestCase):
    def test_short_bash_truncated(self):
        long_res = "bash:" + "echo " * 200
        displayed = selftools._display_resource(long_res)
        self.assertLess(len(displayed), 130)
        self.assertIn("bash:", displayed)

    def test_file_path_untouched(self):
        fp = "/some/path/to/file.py"
        self.assertEqual(selftools._display_resource(fp), fp)

    def test_short_bash_untouched(self):
        short_bash = "bash:ls -la"
        self.assertEqual(selftools._display_resource(short_bash), short_bash)


class TestHumanAgo(unittest.TestCase):
    def test_seconds(self):
        now = selftools.now_ms()
        self.assertEqual(selftools.human_ago(now - 5_000), "5s ago")

    def test_minutes(self):
        now = selftools.now_ms()
        self.assertEqual(selftools.human_ago(now - 120_000), "2m ago")

    def test_hours(self):
        now = selftools.now_ms()
        self.assertEqual(selftools.human_ago(now - 7200_000), "2h ago")

    def test_days(self):
        now = selftools.now_ms()
        self.assertEqual(selftools.human_ago(now - 172_800_000), "2d ago")


class TestToolIntent(unittest.TestCase):
    def test_description(self):
        result = selftools.tool_intent({"tool_input": {"description": "fix bug"}})
        self.assertEqual(result, "fix bug")

    def test_empty(self):
        result = selftools.tool_intent({"tool_input": {}})
        self.assertEqual(result, "unspecified")

    def test_no_input(self):
        result = selftools.tool_intent({})
        self.assertEqual(result, "unspecified")


class TestGitNexusIntegration(unittest.TestCase):
    def test_run_gitnexus_unavailable_does_not_raise(self):
        with patch.object(selftools.shutil, "which", return_value=None):
            self.assertIsNone(selftools.run_gitnexus(["query", "anything"], "/tmp"))

    def test_run_gitnexus_available_executes_command(self):
        with patch.object(selftools.shutil, "which", return_value="/bin/echo"):
            proc = selftools.run_gitnexus(["query", "anything"], "/tmp")

        self.assertIsNotNone(proc)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("query anything", proc.stdout)


# ─── Session management ───


class TestSessionManagement(TempDataMixin, unittest.TestCase):
    def test_register_and_load(self):
        event = {"session_id": "test-sess-1", "cwd": "/tmp"}
        record = selftools.register_session(event, source="test")
        self.assertEqual(record["session_id"], "test-sess-1")
        self.assertEqual(record["status"], "active")

        loaded = selftools.load_session("test-sess-1")
        self.assertEqual(loaded["session_id"], "test-sess-1")

    def test_retire_session(self):
        selftools.register_session({"session_id": "test-sess-2", "cwd": "/tmp"}, source="test")
        record = selftools.load_session("test-sess-2")
        record["status"] = "retired"
        selftools.write_json_atomic(selftools.session_path("test-sess-2"), record)
        loaded = selftools.load_session("test-sess-2")
        self.assertEqual(loaded["status"], "retired")


# ─── Trace / index / timeline ───


class TestTraceAndIndex(TempDataMixin, unittest.TestCase):
    def _write_trace(self, trace_id, resource, operation="modify", session_id="s1", runtime="claude"):
        trace = {
            "trace_id": trace_id,
            "session_id": session_id,
            "tool": "Write",
            "resource_path": resource,
            "operation": operation,
            "intent": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": runtime,
            "actor_type": "agent",
            "role": "implementer",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)
        session = {"session_id": session_id, "runtime": runtime, "role": "implementer"}
        selftools.update_index(resource, trace, session)
        return trace

    def test_write_and_read_trace(self):
        self._write_trace("tr_001", "/tmp/test.py")
        result = selftools.read_trace("tr_001")
        self.assertIsNotNone(result)
        self.assertEqual(result["trace_id"], "tr_001")

    def test_read_nonexistent_trace(self):
        result = selftools.read_trace("tr_nonexistent")
        self.assertIsNone(result)

    def test_index_updated(self):
        self._write_trace("tr_002", "/tmp/indexed.py")
        idx = selftools.load_index("/tmp/indexed.py")
        self.assertEqual(idx["total_ops"], 1)
        self.assertEqual(idx["last_op"], "modify")

    def test_recent_traces(self):
        for i in range(5):
            self._write_trace(f"tr_00{i}", "/tmp/multi.py")
        traces = selftools.recent_traces("/tmp/multi.py", limit=3)
        self.assertEqual(len(traces), 3)


class TestTimeline(TempDataMixin, unittest.TestCase):
    def test_timeline_event_structure(self):
        trace = {
            "trace_id": "tr_tl",
            "session_id": "s1",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
            "tool": "Write",
            "resource_path": "/tmp/tl.py",
            "operation": "modify",
            "intent": "test",
        }
        event = {}
        session = {"role": "implementer", "actor_type": "agent", "runtime": "claude"}
        tl_event = selftools.timeline_event_from_trace(trace, event, session)
        self.assertEqual(tl_event["schema_version"], "aids.timeline.v1")
        self.assertEqual(tl_event["trace_id"], "tr_tl")
        self.assertIn("event_id", tl_event)


# ─── Ratings ───


class TestRatings(TempDataMixin, unittest.TestCase):
    def test_rating_roundtrip(self):
        # Write a trace first
        trace = {
            "trace_id": "tr_rate",
            "session_id": "s1",
            "tool": "Write",
            "resource_path": "/tmp/rate.py",
            "operation": "modify",
            "intent": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)

        # Rate it
        rating = {
            "rating_id": "rt_001",
            "trace_id": "tr_rate",
            "score": "good",
            "comment": "nice work",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
        }
        selftools.append_jsonl(selftools.data_dir() / "ratings" / f"{selftools.today()}.jsonl", rating)

        # Read back
        ratings_file = selftools.data_dir() / "ratings" / f"{selftools.today()}.jsonl"
        lines = ratings_file.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        loaded = json.loads(lines[0])
        self.assertEqual(loaded["score"], "good")


# ─── CLI commands ───


class TestCmdStats(TempDataMixin, unittest.TestCase):
    def _seed_data(self):
        """Seed sessions, traces, timeline, ratings for stats testing."""
        dd = selftools.data_dir()

        # Sessions
        for i, (runtime, role, status) in enumerate([
            ("claude", "implementer", "active"),
            ("claude", "master", "active"),
            ("codex", "implementer", "active"),
            ("bash", "human", "retired"),
        ]):
            sid = f"stats-sess-{i}"
            record = {
                "session_id": sid,
                "runtime": runtime,
                "role": role,
                "status": status,
                "display_name": f"Agent-{i}",
                "started_at": selftools.now_ms(),
                "started_iso": selftools.iso_now(),
            }
            selftools.write_json_atomic(dd / "sessions" / f"{sid}.json", record)

        # Traces
        today_file = selftools.traces_file_for_today()
        for i, (op, runtime, resource) in enumerate([
            ("read", "claude", "/tmp/a.py"),
            ("modify", "claude", "/tmp/a.py"),
            ("execute", "bash", "bash:ls"),
            ("create", "codex", "/tmp/b.py"),
            ("modify", "claude", "/tmp/a.py"),
        ]):
            trace = {
                "trace_id": f"tr_stat_{i}",
                "session_id": f"stats-sess-{i % 4}",
                "tool": "Write" if op != "execute" else "Bash",
                "resource_path": resource,
                "operation": op,
                "intent": "test",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
                "runtime": runtime,
                "actor_type": "agent",
            }
            selftools.append_jsonl(today_file, trace)

        # Timeline
        tl_file = selftools.timeline_file_for_today()
        for i in range(5):
            selftools.append_jsonl(tl_file, {"event_id": f"ev_{i}", "timestamp": selftools.now_ms()})

        # Ratings
        ratings_file = dd / "ratings" / f"{selftools.today()}.jsonl"
        for score in ["good", "good", "bad"]:
            selftools.append_jsonl(ratings_file, {"score": score, "timestamp": selftools.now_ms()})

    def test_stats_human_readable(self):
        self._seed_data()
        args = selftools.build_parser().parse_args(["stats", "--all"])
        with patch("sys.stdout") as mock_out:
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)

    def test_stats_json(self):
        self._seed_data()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"]["total"], 4)
        self.assertEqual(result["traces"]["total"], 5)
        self.assertEqual(result["timeline_events"], 5)
        self.assertEqual(result["ratings"]["total"], 3)
        self.assertIn("top_sessions", result)
        self.assertIn("resources", result)

    def test_stats_date_filter(self):
        self._seed_data()
        # Filter to today only
        today_str = selftools.today()
        args = selftools.build_parser().parse_args(["stats", "--from", today_str, "--to", today_str, "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["traces"]["total"], 5)

    def test_stats_empty(self):
        """Stats on empty data dir should not crash."""
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"]["total"], 0)
        self.assertEqual(result["traces"]["total"], 0)


class TestCmdExport(TempDataMixin, unittest.TestCase):
    def _seed_export_data(self):
        dd = selftools.data_dir()
        session = {
            "session_id": "export-s1",
            "runtime": "codex",
            "role": "implementer",
            "status": "active",
            "display_name": "Export Agent",
            "started_iso": selftools.iso_now(),
            "last_seen_iso": selftools.iso_now(),
        }
        selftools.write_json_atomic(dd / "sessions" / "export-s1.json", session)

        trace = {
            "trace_id": "tr_export_1",
            "session_id": "export-s1",
            "tool": "Write",
            "resource_path": "/tmp/export.py",
            "operation": "modify",
            "intent": "export test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "codex",
            "actor_type": "agent",
            "role": "implementer",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)

        timeline = {
            "event_id": "ev_export_1",
            "trace_id": "tr_export_1",
            "session_id": "export-s1",
            "resource": "/tmp/export.py",
            "tool": "Write",
            "operation": "modify",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
        }
        selftools.append_jsonl(selftools.timeline_file_for_today(), timeline)

        rating = {
            "rating_id": "rt_export_1",
            "trace_id": "tr_export_1",
            "rater_session_id": "export-s1",
            "score": "good",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
        }
        selftools.append_jsonl(dd / "ratings" / f"{selftools.today()}.jsonl", rating)

    def test_export_default_json_all_with_metadata(self):
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["format"], "json")
        self.assertEqual(result["metadata"]["type"], "all")
        self.assertEqual(result["metadata"]["record_count"], 4)
        self.assertIn("exported_at", result["metadata"])
        self.assertEqual(len(result["data"]["traces"]), 1)
        self.assertEqual(len(result["data"]["sessions"]), 1)

    def test_export_jsonl_trace_filter(self):
        self._seed_export_data()
        args = selftools.build_parser().parse_args([
            "export", "--format", "jsonl", "--type", "traces",
            "--session", "export-s1", "--resource", "/tmp/export.py",
        ])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        lines = [json.loads(line) for line in captured.getvalue().strip().splitlines()]
        self.assertIn("metadata", lines[0])
        self.assertEqual(lines[0]["metadata"]["record_count"], 1)
        self.assertEqual(lines[1]["trace_id"], "tr_export_1")

    def test_export_csv_traces_includes_metadata_columns(self):
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--format", "csv", "--type", "traces"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        rows = list(csv.reader(io.StringIO(captured.getvalue())))
        self.assertIn("exported_at", rows[0])
        self.assertIn("trace_id", rows[0])
        self.assertEqual(rows[1][rows[0].index("record_count")], "1")
        self.assertEqual(rows[1][rows[0].index("trace_id")], "tr_export_1")

    def test_export_csv_rejects_sessions(self):
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--format", "csv", "--type", "sessions"])
        import io
        captured_err = io.StringIO()
        with patch("sys.stderr", captured_err):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 2)
        self.assertIn("CSV output is only supported", captured_err.getvalue())

    def test_export_json_type_traces_only(self):
        """export --type traces returns only trace records."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--type", "traces"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["type"], "traces")
        self.assertIsInstance(result["data"], list)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["trace_id"], "tr_export_1")

    def test_export_json_type_ratings_only(self):
        """export --type ratings returns only rating records."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--type", "ratings"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["type"], "ratings")
        self.assertIsInstance(result["data"], list)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["rating_id"], "rt_export_1")

    def test_export_json_type_sessions_only(self):
        """export --type sessions returns only session records."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--type", "sessions"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["type"], "sessions")
        self.assertIsInstance(result["data"], list)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["session_id"], "export-s1")

    def test_export_json_days_filter(self):
        """export --days 1 returns today's data."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--days", "1"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["record_count"], 4)

    def test_export_json_date_range_filter(self):
        """export --from/--to filters by date."""
        self._seed_export_data()
        today_str = selftools.today()
        args = selftools.build_parser().parse_args(["export", "--from", today_str, "--to", today_str])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["record_count"], 4)

    def test_export_json_date_range_excludes_old(self):
        """export --from far-future --to far-future returns 0 records."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--from", "2099-01-01", "--to", "2099-12-31"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["record_count"], 0)

    def test_export_json_session_filter(self):
        """export --session filters by session_id."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--session", "export-s1"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        # traces and timeline match session, sessions matches, ratings match
        self.assertGreater(result["metadata"]["record_count"], 0)

    def test_export_json_session_filter_no_match(self):
        """export --session with nonexistent session returns 0 records."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--session", "nonexistent-session"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["record_count"], 0)

    def test_export_json_output_to_file(self):
        """export --output writes to a file instead of stdout."""
        self._seed_export_data()
        outfile = os.path.join(self._tmpdir, "export_out.json")
        args = selftools.build_parser().parse_args(["export", "--output", outfile])
        with patch("sys.stdout"):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(outfile))
        with open(outfile, "r", encoding="utf-8") as f:
            result = json.loads(f.read())
        self.assertEqual(result["metadata"]["format"], "json")
        self.assertEqual(result["metadata"]["record_count"], 4)

    def test_export_empty_data(self):
        """export on empty data dir does not crash."""
        args = selftools.build_parser().parse_args(["export"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["metadata"]["record_count"], 0)

    def test_export_csv_timeline(self):
        """export --format csv --type timeline produces valid CSV."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--format", "csv", "--type", "timeline"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 0)
        rows = list(csv.reader(io.StringIO(captured.getvalue())))
        self.assertGreaterEqual(len(rows), 2)  # header + at least 1 data row
        self.assertIn("exported_at", rows[0])
        self.assertIn("event_id", rows[0])
        self.assertEqual(rows[1][rows[0].index("record_count")], "1")

    def test_export_csv_ratings_rejected(self):
        """export --format csv --type ratings is rejected (not flat enough)."""
        self._seed_export_data()
        args = selftools.build_parser().parse_args(["export", "--format", "csv", "--type", "ratings"])
        import io
        captured_err = io.StringIO()
        with patch("sys.stderr", captured_err):
            rc = selftools.cmd_export(args)
        self.assertEqual(rc, 2)
        self.assertIn("CSV output is only supported", captured_err.getvalue())


class TestCmdQuery(TempDataMixin, unittest.TestCase):
    def _seed_query_data(self):
        resource_file = Path(self._tmpdir) / "README.md"
        resource_file.write_text("# Query Test\n", encoding="utf-8")
        resource = selftools.normalize_resource(str(resource_file))
        session = {
            "session_id": "query-s1",
            "runtime": "codex",
            "role": "implementer",
            "status": "active",
            "display_name": "Query Agent",
            "goal": "test query router",
        }
        selftools.write_json_atomic(selftools.session_path("query-s1"), session)
        trace = {
            "trace_id": "tr_query_1",
            "session_id": "query-s1",
            "tool": "Write",
            "resource_path": resource,
            "operation": "modify",
            "intent": "query router test",
            "pre_hash": None,
            "post_hash": selftools.sha256_file(resource_file),
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "codex",
            "actor_type": "agent",
            "role": "implementer",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)
        selftools.update_index(resource, trace, session)
        rating = {
            "rating_id": "rt_query_1",
            "trace_id": "tr_query_1",
            "rater_session_id": "query-s1",
            "score": "good",
            "comment": "works",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
        }
        selftools.append_jsonl(selftools.data_dir() / "ratings" / f"{selftools.today()}.jsonl", rating)
        return resource_file

    def test_query_json_file_default_modules(self):
        resource_file = self._seed_query_data()
        args = selftools.build_parser().parse_args(["q", str(resource_file), "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_query(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["schema_version"], "aids.query.v1")
        self.assertEqual(result["target"]["kind"], "file")
        self.assertIn("history", result["modules"])
        modules = {item["module"]: item for item in result["results"]}
        self.assertEqual(modules["history"]["status"], "ok")
        self.assertEqual(modules["ratings"]["distribution"]["good"], 1)

    def test_query_include_exclude_overrides_config(self):
        resource_file = self._seed_query_data()
        selftools.write_json_atomic(selftools.data_dir() / "config.json", {
            "query": {"enabled_modules": ["identity", "history", "ratings"], "default_limit": 2}
        })
        args = selftools.build_parser().parse_args([
            "query", str(resource_file), "--include", "file_chain,ratings", "--exclude", "ratings", "--json"
        ])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_query(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["modules"], ["history"])
        self.assertEqual(result["limit"], 2)

    def test_query_trace_signature_and_rating(self):
        self._seed_query_data()
        args = selftools.build_parser().parse_args([
            "q", "tr_query_1", "--json", "--include", "history,signature,ratings"
        ])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_query(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["target"]["kind"], "trace")
        modules = {item["module"]: item for item in result["results"]}
        self.assertEqual(modules["signature"]["items"][0]["status"], "hash_present")
        self.assertEqual(modules["ratings"]["distribution"]["good"], 1)

    def test_ask_unknown_compact_output(self):
        self._seed_query_data()
        args = selftools.build_parser().parse_args(["ask", "query", "router", "--limit", "2"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_query(args)
        self.assertEqual(rc, 0)
        out = captured.getvalue()
        self.assertIn("AIDS query", out)
        self.assertIn("history", out)

    def test_ask_detects_embedded_file_path(self):
        resource_file = self._seed_query_data()
        args = selftools.build_parser().parse_args(["ask", "who", "changed", str(resource_file), "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_query(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["target"]["kind"], "file")


class TestCmdTimeline(TempDataMixin, unittest.TestCase):
    def test_timeline_empty(self):
        args = selftools.build_parser().parse_args(["timeline"])
        rc = selftools.cmd_timeline(args)
        self.assertEqual(rc, 1)  # No events today

    def test_timeline_with_events(self):
        tl_file = selftools.timeline_file_for_today()
        for i in range(3):
            selftools.append_jsonl(tl_file, {
                "event_id": f"ev_{i}",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
                "tool": "Write",
                "session_id": "s1",
                "resource": "/tmp/test.py",
                "runtime": "claude",
                "actor_type": "agent",
            })
        args = selftools.build_parser().parse_args(["timeline"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_timeline(args)
        self.assertEqual(rc, 0)
        lines = captured.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)

    def test_timeline_json(self):
        tl_file = selftools.timeline_file_for_today()
        selftools.append_jsonl(tl_file, {"event_id": "ev_1", "timestamp": selftools.now_ms()})
        args = selftools.build_parser().parse_args(["timeline", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_timeline(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["count"], 1)


class TestCmdWhoTouched(TempDataMixin, unittest.TestCase):
    def test_no_traces(self):
        args = selftools.build_parser().parse_args(["who-touched", "/tmp/nonexistent.py"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 1)

    def test_with_traces(self):
        # Use the resolved path so normalize_resource matches on macOS (/tmp -> /private/tmp)
        resource = str(Path("/tmp/touched.py").resolve())
        # Seed a session so recent_traces can enrich the trace
        session = {"session_id": "s_wt", "runtime": "claude", "role": "implementer", "display_name": "Tester", "status": "active"}
        selftools.write_json_atomic(selftools.session_path("s_wt"), session)
        # Seed a trace
        trace = {
            "trace_id": "tr_wt",
            "session_id": "s_wt",
            "tool": "Write",
            "resource_path": resource,
            "operation": "modify",
            "intent": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
            "role": "implementer",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)
        selftools.update_index(resource, trace, session)

        args = selftools.build_parser().parse_args(["who-touched", resource])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_who_touched(args)
        self.assertEqual(rc, 0)
        self.assertIn("tr_wt", captured.getvalue())


class TestCmdListSessions(TempDataMixin, unittest.TestCase):
    def test_empty(self):
        args = selftools.build_parser().parse_args(["list-sessions"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)

    def test_with_sessions(self):
        for i in range(3):
            record = {
                "session_id": f"ls-{i}",
                "runtime": "claude",
                "role": "implementer",
                "status": "active",
                "display_name": f"Agent-{i}",
            }
            selftools.write_json_atomic(selftools.session_path(f"ls-{i}"), record)

        args = selftools.build_parser().parse_args(["list-sessions", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(len(result["sessions"]), 3)

    def test_filter_by_runtime(self):
        for rt in ["claude", "codex", "bash"]:
            record = {
                "session_id": f"ls-{rt}",
                "runtime": rt,
                "role": "implementer",
                "status": "active",
            }
            selftools.write_json_atomic(selftools.session_path(f"ls-{rt}"), record)

        args = selftools.build_parser().parse_args(["list-sessions", "--runtime", "claude", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["runtime"], "claude")


class TestCmdDoctor(TempDataMixin, unittest.TestCase):
    def test_doctor_basic(self):
        args = selftools.build_parser().parse_args(["doctor", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_doctor(args)
        result = json.loads(captured.getvalue())
        # Data dirs exist in temp dir, so core checks should pass
        self.assertIn("checks", result)
        data_checks = [c for c in result["checks"] if c["name"].endswith("_dir")]
        self.assertTrue(all(c["ok"] for c in data_checks), f"Data dir checks failed: {data_checks}")

    def test_doctor_clean_locks_removes_stale(self):
        """doctor --clean-locks removes stale lock files."""
        dd = selftools.data_dir()
        locks_dir = dd / "locks"
        locks_dir.mkdir(parents=True, exist_ok=True)

        fake_pid = 999999999
        stale_lock = locks_dir / "test-stale.lock"
        stale_lock.write_text(json.dumps({"pid": fake_pid, "ts": 0}), encoding="utf-8")
        import time as _time
        old_time = _time.time() - selftools.FileLock.STALE_SECONDS - 60
        os.utime(stale_lock, (old_time, old_time))

        self.assertTrue(stale_lock.exists())
        args = selftools.build_parser().parse_args(["doctor", "--clean-locks", "--json"])
        import io
        captured = io.StringIO()
        # Prevent ensure_layout's clean_all_stale_locks from removing lock before doctor scans
        with patch.object(selftools, "clean_all_stale_locks"):
            with patch("sys.stdout", captured):
                rc = selftools.cmd_doctor(args)
        result = json.loads(captured.getvalue())
        clean_check = [c for c in result["checks"] if c["name"] == "clean_locks"]
        self.assertEqual(len(clean_check), 1)
        self.assertTrue(clean_check[0]["ok"])
        self.assertIn("removed 1/1", clean_check[0]["detail"])
        self.assertFalse(stale_lock.exists(), "Stale lock should be deleted")

    def test_doctor_clean_locks_preserves_active(self):
        """doctor --clean-locks keeps active (current PID) lock files."""
        dd = selftools.data_dir()
        locks_dir = dd / "locks"
        locks_dir.mkdir(parents=True, exist_ok=True)

        active_lock = locks_dir / "test-active.lock"
        active_lock.write_text(json.dumps({"pid": os.getpid(), "ts": selftools.now_ms()}), encoding="utf-8")

        args = selftools.build_parser().parse_args(["doctor", "--clean-locks", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_doctor(args)
        result = json.loads(captured.getvalue())
        self.assertTrue(active_lock.exists(), "Active lock should be preserved")
        clean_check = [c for c in result["checks"] if c["name"] == "clean_locks"]
        self.assertEqual(len(clean_check), 0)

    def test_doctor_without_clean_locks_no_deletion(self):
        """doctor without --clean-locks does NOT delete stale locks."""
        dd = selftools.data_dir()
        locks_dir = dd / "locks"
        locks_dir.mkdir(parents=True, exist_ok=True)

        fake_pid = 999999999
        stale_lock = locks_dir / "test-noclean.lock"
        stale_lock.write_text(json.dumps({"pid": fake_pid, "ts": 0}), encoding="utf-8")
        import time as _time
        old_time = _time.time() - selftools.FileLock.STALE_SECONDS - 60
        os.utime(stale_lock, (old_time, old_time))

        args = selftools.build_parser().parse_args(["doctor", "--json"])
        import io
        captured = io.StringIO()
        # Prevent ensure_layout's clean_all_stale_locks from removing lock before doctor scans
        with patch.object(selftools, "clean_all_stale_locks"):
            with patch("sys.stdout", captured):
                rc = selftools.cmd_doctor(args)
        self.assertTrue(stale_lock.exists(), "Without --clean-locks, stale lock should remain")


class TestBuildParser(unittest.TestCase):
    def test_all_subcommands_registered(self):
        p = selftools.build_parser()
        # Parse each subcommand to verify it exists
        for cmd in ["stats", "export", "q", "query", "ask", "timeline", "doctor", "list-sessions", "who-touched", "op-chain", "rate", "heartbeat", "whois", "session-info", "retire-session", "register-session", "commit-stamp", "verify", "impact"]:
            if cmd == "session-info":
                args = p.parse_args([cmd, "test-id"])
            elif cmd == "retire-session":
                args = p.parse_args([cmd, "test-id"])
            elif cmd == "whois":
                args = p.parse_args([cmd, "test-id"])
            elif cmd == "heartbeat":
                args = p.parse_args([cmd, "test-id"])
            elif cmd == "who-touched":
                args = p.parse_args([cmd, "/tmp/test"])
            elif cmd == "op-chain":
                args = p.parse_args([cmd, "/tmp/test"])
            elif cmd in {"q", "query", "ask"}:
                args = p.parse_args([cmd, "/tmp/test"])
            elif cmd == "rate":
                args = p.parse_args([cmd, "tr_001", "good"])
            elif cmd == "impact":
                args = p.parse_args([cmd, "/tmp/test"])
            else:
                args = p.parse_args([cmd])
            self.assertTrue(hasattr(args, "func"), f"Subcommand '{cmd}' missing func")

    def test_stats_flags(self):
        p = selftools.build_parser()
        args = p.parse_args(["stats", "--all", "--json", "--days", "3"])
        self.assertTrue(args.json)
        self.assertTrue(getattr(args, "all"))
        self.assertEqual(args.days, 3)

    def test_stats_date_range(self):
        p = selftools.build_parser().parse_args(["stats", "--from", "2026-01-01", "--to", "2026-01-31"])
        self.assertEqual(getattr(p, "from_date"), "2026-01-01")
        self.assertEqual(getattr(p, "to_date"), "2026-01-31")

    def test_export_defaults_and_flags(self):
        p = selftools.build_parser()
        args = p.parse_args(["export"])
        self.assertEqual(args.format, "json")
        self.assertEqual(args.type, "all")
        args = p.parse_args(["export", "--format", "csv", "--type", "timeline", "--days", "3"])
        self.assertEqual(args.format, "csv")
        self.assertEqual(args.type, "timeline")
        self.assertEqual(args.days, 3)


class TestDetectResources(unittest.TestCase):
    def test_bash_command_not_truncated(self):
        """Long bash commands must NOT be truncated in resource_path."""
        long_cmd = "echo " + "x " * 300
        resources = selftools.detect_resources("Bash", {"command": long_cmd}, "/tmp")
        bash_res = [r for r in resources if r.startswith("bash:")]
        self.assertEqual(len(bash_res), 1)
        self.assertEqual(bash_res[0], f"bash:{long_cmd}")

    def test_bash_redirect_target_extracted(self):
        resources = selftools.detect_resources(
            "Bash", {"command": 'echo "hello" > /tmp/out.txt'}, "/tmp"
        )
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertTrue(any("out.txt" in p for p in paths))

    def test_bash_tee_target_extracted(self):
        resources = selftools.detect_resources(
            "Bash", {"command": "cat /tmp/in.txt | tee /tmp/out.txt"}, "/tmp"
        )
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertTrue(any("out.txt" in p for p in paths))

    def test_bash_append_target_extracted(self):
        resources = selftools.detect_resources(
            "Bash", {"command": "echo line >> /tmp/log.txt"}, "/tmp"
        )
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertTrue(any("log.txt" in p for p in paths))

    def test_bash_cp_target_extracted(self):
        resources = selftools.detect_resources(
            "Bash", {"command": "cp /tmp/a.txt /tmp/b.txt"}, "/tmp"
        )
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertTrue(any("b.txt" in p for p in paths))

    def test_write_tool_extracts_file_path(self):
        resources = selftools.detect_resources(
            "Write", {"file_path": "/tmp/test.py", "content": "pass"}, "/tmp"
        )
        self.assertEqual(len(resources), 1)
        self.assertIn("test.py", resources[0])

    def test_read_tool_extracts_file_path(self):
        resources = selftools.detect_resources(
            "Read", {"file_path": "/tmp/test.py"}, "/tmp"
        )
        self.assertEqual(len(resources), 1)
        self.assertIn("test.py", resources[0])

    def test_mcp_tool_creates_mcp_resource(self):
        resources = selftools.detect_resources(
            "mcp__aha__start_task", {"taskId": "abc"}, "/tmp"
        )
        self.assertEqual(len(resources), 1)
        self.assertTrue(resources[0].startswith("mcp:"))

    def test_empty_bash_command(self):
        resources = selftools.detect_resources("Bash", {"command": ""}, "/tmp")
        bash_res = [r for r in resources if r.startswith("bash:")]
        self.assertEqual(len(bash_res), 1)
        self.assertEqual(bash_res[0], "bash:")

    def test_dedup_preserves_order(self):
        resources = selftools.detect_resources(
            "Bash", {"command": "cp /tmp/a.txt /tmp/a.txt"}, "/tmp"
        )
        paths = [r for r in resources if not r.startswith("bash:")]
        self.assertEqual(len(paths), 1)


class TestIndexKeyDualLayer(unittest.TestCase):
    def test_short_resource_uses_base64(self):
        key = selftools.index_key("/tmp/short.py")
        self.assertFalse(key.startswith("sha256-"))

    def test_long_resource_uses_hash(self):
        key = selftools.index_key("bash:" + "x " * 300)
        self.assertTrue(key.startswith("sha256-"))
        self.assertLess(len(key), 80)

    def test_hash_key_still_unique(self):
        k1 = selftools.index_key("bash:" + "x " * 300)
        k2 = selftools.index_key("bash:" + "y " * 300)
        self.assertNotEqual(k1, k2)

    def test_load_index_preserves_full_resource_path(self):
        long_resource = "bash:" + "echo " * 200
        idx = {"resource_path": long_resource, "trace_ids": [], "total_ops": 0}
        path = selftools.index_path(long_resource)
        path.parent.mkdir(parents=True, exist_ok=True)
        selftools.write_json_atomic(path, idx)
        loaded = selftools.load_index(long_resource)
        self.assertEqual(loaded.get("resource_path"), long_resource)


class TestCmdRegisterSessionCLI(TempDataMixin, unittest.TestCase):
    def test_register_via_cli(self):
        import io
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


class TestCmdRateCLI(TempDataMixin, unittest.TestCase):
    def _seed_trace(self, trace_id="tr_rate_cli"):
        selftools.append_jsonl(selftools.traces_file_for_today(), {
            "trace_id": trace_id,
            "session_id": "s1",
            "tool": "Write",
            "resource_path": "/tmp/rate_cli.py",
            "operation": "modify",
            "intent": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
        })

    def test_rate_existing_trace(self):
        import io
        self._seed_trace()
        args = selftools.build_parser().parse_args(["rate", "tr_rate_cli", "good", "nice work"])
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_rate(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["score"], "good")
        self.assertEqual(result["comment"], "nice work")

    def test_rate_nonexistent_trace(self):
        import io
        args = selftools.build_parser().parse_args(["rate", "tr_ghost", "bad", "missing"])
        rc = selftools.cmd_rate(args)
        self.assertEqual(rc, 1)

    def test_duplicate_rating_rejected(self):
        """INV-7: same rater cannot rate same trace twice."""
        import io
        self._seed_trace("tr_dup")
        args1 = selftools.build_parser().parse_args(["rate", "tr_dup", "good", "first"])
        captured1 = io.StringIO()
        with patch("sys.stdout", captured1):
            rc1 = selftools.cmd_rate(args1)
        self.assertEqual(rc1, 0)

        args2 = selftools.build_parser().parse_args(["rate", "tr_dup", "bad", "second"])
        rc2 = selftools.cmd_rate(args2)
        self.assertEqual(rc2, 1, "Duplicate rating should be rejected (INV-7)")

    def test_different_rater_allowed(self):
        """Different rater can rate the same trace."""
        self._seed_trace("tr_multi")
        # Rater 1
        with patch.dict(os.environ, {"AIDS_SESSION_ID": "rater-1"}):
            args1 = selftools.build_parser().parse_args(["rate", "tr_multi", "good", "from r1"])
            rc1 = selftools.cmd_rate(args1)
        self.assertEqual(rc1, 0)

        # Rater 2
        with patch.dict(os.environ, {"AIDS_SESSION_ID": "rater-2"}):
            args2 = selftools.build_parser().parse_args(["rate", "tr_multi", "bad", "from r2"])
            rc2 = selftools.cmd_rate(args2)
        self.assertEqual(rc2, 0, "Different rater should be allowed")


# ─── compute_agent_id ───


class TestComputeAgentId(unittest.TestCase):
    def test_deterministic(self):
        """Same inputs produce same agent_id."""
        id1 = selftools.compute_agent_id("Frontend Agent", "implementer", "team-1")
        id2 = selftools.compute_agent_id("Frontend Agent", "implementer", "team-1")
        self.assertEqual(id1, id2)

    def test_format_prefix(self):
        """agent_id starts with 'agent-'."""
        aid = selftools.compute_agent_id("Bot", "tester")
        self.assertTrue(aid.startswith("agent-"), f"Expected 'agent-' prefix, got: {aid}")

    def test_hash_length(self):
        """agent_id has the expected format: 'agent-' + 16 hex chars."""
        aid = selftools.compute_agent_id("Bot", "tester")
        hex_part = aid[len("agent-"):]
        self.assertEqual(len(hex_part), 16, f"Expected 16 hex chars, got: {hex_part}")
        self.assertTrue(all(c in "0123456789abcdef" for c in hex_part))

    def test_different_names_produce_different_ids(self):
        id1 = selftools.compute_agent_id("Alice", "implementer")
        id2 = selftools.compute_agent_id("Bob", "implementer")
        self.assertNotEqual(id1, id2)

    def test_different_roles_produce_different_ids(self):
        id1 = selftools.compute_agent_id("Agent", "implementer")
        id2 = selftools.compute_agent_id("Agent", "reviewer")
        self.assertNotEqual(id1, id2)

    def test_different_teams_produce_different_ids(self):
        id1 = selftools.compute_agent_id("Agent", "implementer", "team-A")
        id2 = selftools.compute_agent_id("Agent", "implementer", "team-B")
        self.assertNotEqual(id1, id2)

    def test_none_team_equals_empty_team(self):
        id1 = selftools.compute_agent_id("Agent", "impl", None)
        id2 = selftools.compute_agent_id("Agent", "impl", "")
        self.assertEqual(id1, id2)

    def test_empty_inputs_stable(self):
        id1 = selftools.compute_agent_id("", "", "")
        id2 = selftools.compute_agent_id("", "", "")
        self.assertEqual(id1, id2)


class TestIdentityDisclosure(unittest.TestCase):
    def test_identity_lines_include_agent_and_session(self):
        lines = selftools.identity_lines({
            "display_name": "Codex",
            "role": "developer",
            "runtime": "codex",
            "model": "gpt-5.5",
            "agent_id": "agent-abc123",
            "session_id": "sess-1",
        })
        text = "\n".join(lines)
        self.assertIn("agent_id=agent-abc123", text)
        self.assertIn("session_id=sess-1", text)
        self.assertIn("runtime=codex", text)

    def test_compact_trace_keeps_visible_identity(self):
        compact = selftools._compact_trace({
            "trace_id": "tr_id",
            "agent_id": "agent-abc123",
            "display_name": "Codex",
            "model": "gpt-5.5",
            "role": "developer",
            "runtime": "codex",
        })
        self.assertEqual(compact["agent_id"], "agent-abc123")
        self.assertEqual(compact["display_name"], "Codex")
        self.assertEqual(compact["model"], "gpt-5.5")


# ─── detect_query_target — agent-prefix ───


class TestDetectQueryTargetAgentPrefix(TempDataMixin, unittest.TestCase):
    def _register_agent_session(self, agent_id: str, session_id: str, role: str = "implementer") -> None:
        """Create a session file with the given agent_id."""
        record = {
            "session_id": session_id,
            "agent_id": agent_id,
            "role": role,
            "runtime": "claude",
            "status": "active",
            "display_name": f"Agent-{agent_id[:8]}",
        }
        selftools.write_json_atomic(selftools.session_path(session_id), record)

    def test_agent_prefix_returns_agent_kind(self):
        """agent-<hex> query returns kind='agent'."""
        aid = selftools.compute_agent_id("TestBot", "implementer")
        self._register_agent_session(aid, "sess-agent-1")

        result = selftools.detect_query_target(aid)
        self.assertEqual(result["kind"], "agent")
        self.assertEqual(result["id"], aid)
        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["agent_id"], aid)

    def test_agent_prefix_no_match_returns_unknown(self):
        """agent-<hex> with no matching session falls through to unknown."""
        result = selftools.detect_query_target("agent-deadbeef12345678")
        # No session registered with this agent_id, so it should not resolve as "agent"
        # It will try session lookup next, but "agent-deadbeef12345678" is not a valid session
        self.assertNotEqual(result["kind"], "agent")

    def test_agent_prefix_multiple_sessions(self):
        """Multiple sessions with same agent_id are all returned."""
        aid = selftools.compute_agent_id("MultiBot", "implementer", "team-1")
        self._register_agent_session(aid, "sess-multi-1")
        self._register_agent_session(aid, "sess-multi-2")

        result = selftools.detect_query_target(aid)
        self.assertEqual(result["kind"], "agent")
        self.assertEqual(len(result["sessions"]), 2)

    def test_trace_prefix_takes_priority_over_agent(self):
        """tr_ prefix is resolved before agent- prefix."""
        aid = selftools.compute_agent_id("TestBot", "implementer")
        self._register_agent_session(aid, "sess-priority")

        # Write a trace with tr_ prefix
        trace = {
            "trace_id": "tr_priority_test",
            "session_id": "sess-priority",
            "tool": "Write",
            "resource_path": "/tmp/test.py",
            "operation": "modify",
            "intent": "priority test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)

        result = selftools.detect_query_target(f"tr_priority_test {aid}")
        self.assertEqual(result["kind"], "trace")
        self.assertEqual(result["id"], "tr_priority_test")

    def test_rating_prefix_takes_priority_over_agent(self):
        """rt_ prefix is resolved before agent- prefix."""
        aid = selftools.compute_agent_id("TestBot", "implementer")
        self._register_agent_session(aid, "sess-rt-priority")

        # Write a rating
        rating = {
            "rating_id": "rt_priority_test",
            "trace_id": "tr_x",
            "score": "good",
            "comment": "test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
        }
        selftools.append_jsonl(
            selftools.data_dir() / "ratings" / f"{selftools.today()}.jsonl", rating
        )

        result = selftools.detect_query_target(f"rt_priority_test {aid}")
        self.assertEqual(result["kind"], "rating")
        self.assertEqual(result["id"], "rt_priority_test")

    def test_agent_prefix_in_multi_token_query(self):
        """agent-<hex> as any token in query triggers agent resolution."""
        aid = selftools.compute_agent_id("TokenBot", "implementer")
        self._register_agent_session(aid, "sess-token")

        result = selftools.detect_query_target(f"some words {aid} more words")
        self.assertEqual(result["kind"], "agent")
        self.assertEqual(result["id"], aid)

    def test_register_session_assigns_agent_id(self):
        """register_session computes and stores agent_id."""
        os.environ["AIDS_SESSION_ID"] = "sess-auto-aid"
        os.environ["AIDS_DISPLAY_NAME"] = "AutoAgent"
        os.environ["AIDS_ROLE"] = "implementer"
        try:
            record = selftools.register_session({"session_id": "sess-auto-aid", "cwd": "/tmp"}, source="test")
            self.assertTrue(record["agent_id"].startswith("agent-"))

            # Query by agent_id
            result = selftools.detect_query_target(record["agent_id"])
            self.assertEqual(result["kind"], "agent")
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)


# ─── Integration: aids verify ───


class TestCmdVerifyIntegration(TempDataMixin, unittest.TestCase):
    def _write_trace(self, trace_id, resource, operation="modify", session_id="s1"):
        trace = {
            "trace_id": trace_id,
            "session_id": session_id,
            "tool": "Write",
            "resource_path": resource,
            "operation": operation,
            "intent": "verify test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "claude",
            "actor_type": "agent",
            "role": "implementer",
        }
        selftools.append_jsonl(selftools.traces_file_for_today(), trace)
        return trace

    def _rewrite_trace_records(self, updates):
        from datetime import date
        trace_path = selftools.data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        rewritten = []
        for line in lines:
            record = json.loads(line)
            patch = updates.get(record.get("trace_id"))
            if patch:
                record.update(patch)
            rewritten.append(json.dumps(record, ensure_ascii=False))
        trace_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    def test_verify_empty_traces(self):
        """aids verify with no traces returns error code."""
        args = selftools.build_parser().parse_args(["verify"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 1)

    def test_verify_single_trace_passes(self):
        """Single trace with valid chain_hash passes verification."""
        trace = self._write_trace("tr_verify_1", "/tmp/verify.py")
        # Ensure chain_hash exists (appended by post-tool-use in real flow)
        # We need to compute it manually for unit test
        selftools.ensure_layout()
        from datetime import date
        trace_path = selftools.data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        chain_hash = selftools._chain_hash_for_trace(trace, None)
        trace["chain_hash"] = chain_hash
        # Rewrite the trace file with chain_hash
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        updated = []
        for line in lines:
            d = json.loads(line)
            if d.get("trace_id") == "tr_verify_1":
                d["chain_hash"] = chain_hash
            updated.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

        args = selftools.build_parser().parse_args(["verify"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 0, f"verify should pass: {captured.getvalue()}")
        self.assertIn("verified", captured.getvalue().lower())

    def test_verify_json_output(self):
        """aids verify --json returns structured JSON output."""
        trace = self._write_trace("tr_verify_json", "/tmp/verify_json.py")
        chain_hash = selftools._chain_hash_for_trace(trace, None)
        trace["chain_hash"] = chain_hash
        from datetime import date
        trace_path = selftools.data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        updated = []
        for line in lines:
            d = json.loads(line)
            if d.get("trace_id") == "tr_verify_json":
                d["chain_hash"] = chain_hash
            updated.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

        args = selftools.build_parser().parse_args(["verify", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertIn("total_traces", result)
        self.assertIn("verified_ok", result)
        self.assertIn("errors", result)
        self.assertIn("config_violations", result)
        self.assertTrue(result["passed"])

    def test_verify_detects_tampered_trace(self):
        """aids verify detects a tampered chain_hash."""
        trace = self._write_trace("tr_tamper", "/tmp/tamper.py")
        chain_hash = selftools._chain_hash_for_trace(trace, None)
        from datetime import date
        # Step 1: write chain_hash into the file
        trace_path = selftools.data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        updated = []
        for line in lines:
            d = json.loads(line)
            if d.get("trace_id") == "tr_tamper":
                d["chain_hash"] = chain_hash
            updated.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
        # Step 2: tamper — modify the trace_id (part of chain computation)
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        tampered = []
        for line in lines:
            d = json.loads(line)
            if d.get("trace_id") == "tr_tamper":
                d["trace_id"] = "TAMPERED_ID"
            tampered.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(tampered) + "\n", encoding="utf-8")

        args = selftools.build_parser().parse_args(["verify", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertNotEqual(rc, 0, "verify should detect tampering")
        result = json.loads(captured.getvalue())
        self.assertGreater(len(result["errors"]), 0)

    def test_verify_treats_legacy_concurrent_fork_as_warning(self):
        """Legacy concurrent writers can create a valid non-linear chain fork."""
        base = self._write_trace("tr_fork_base", "/tmp/fork.py", session_id="s1")
        base_hash = selftools._chain_hash_for_trace(base, None)
        linear = self._write_trace("tr_fork_linear", "/tmp/fork.py", session_id="s1")
        linear_hash = selftools._chain_hash_for_trace(linear, base_hash)
        forked = self._write_trace("tr_fork_branch", "/tmp/fork.py", session_id="s2")
        forked_hash = selftools._chain_hash_for_trace(forked, base_hash)
        self._rewrite_trace_records({
            "tr_fork_base": {"chain_hash": base_hash},
            "tr_fork_linear": {"chain_hash": linear_hash},
            "tr_fork_branch": {"chain_hash": forked_hash},
        })

        args = selftools.build_parser().parse_args(["verify", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 0, f"forked legacy chain should warn, not fail: {captured.getvalue()}")
        result = json.loads(captured.getvalue())
        self.assertTrue(result["passed"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["parent_trace_id"], "tr_fork_base")

    def test_verify_specific_trace_id(self):
        """aids verify <trace_id> verifies only that trace."""
        trace = self._write_trace("tr_specific", "/tmp/specific.py")
        chain_hash = selftools._chain_hash_for_trace(trace, None)
        trace["chain_hash"] = chain_hash
        from datetime import date
        trace_path = selftools.data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        updated = []
        for line in lines:
            d = json.loads(line)
            if d.get("trace_id") == "tr_specific":
                d["chain_hash"] = chain_hash
            updated.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

        args = selftools.build_parser().parse_args(["verify", "tr_specific"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 0, f"verify <trace_id> should pass: {captured.getvalue()}")

    def test_verify_nonexistent_trace(self):
        """aids verify <nonexistent> returns error."""
        args = selftools.build_parser().parse_args(["verify", "tr_ghost_xyz"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 1)

    def test_verify_legacy_trace_without_chain_hash(self):
        """Legacy traces without chain_hash pass verification."""
        self._write_trace("tr_legacy", "/tmp/legacy.py")
        # No chain_hash field — legacy trace

        args = selftools.build_parser().parse_args(["verify", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_verify(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertTrue(result["passed"])


# ─── Protected config keys ───


class TestProtectedConfigKeys(unittest.TestCase):
    def test_protected_keys_defined(self):
        """PROTECTED_CONFIG_KEYS has expected entries."""
        self.assertIn("signature.enabled", selftools.PROTECTED_CONFIG_KEYS)
        self.assertIn("signature.strategy", selftools.PROTECTED_CONFIG_KEYS)
        self.assertIn("impact.enabled", selftools.PROTECTED_CONFIG_KEYS)
        self.assertTrue(selftools.PROTECTED_CONFIG_KEYS["signature.enabled"])
        self.assertEqual(selftools.PROTECTED_CONFIG_KEYS["signature.strategy"], "hash_chain")
        self.assertTrue(selftools.PROTECTED_CONFIG_KEYS["impact.enabled"])

    def test_enforce_protected_config_overrides_false(self):
        """_enforce_protected_config forces protected keys to required values."""
        config = {
            "signature": {"enabled": False, "strategy": "disabled"},
            "impact": {"enabled": False},
        }
        result = selftools._enforce_protected_config(config)
        self.assertTrue(result["signature"]["enabled"])
        self.assertEqual(result["signature"]["strategy"], "hash_chain")
        self.assertTrue(result["impact"]["enabled"])

    def test_enforce_protected_config_creates_missing_keys(self):
        """_enforce_protected_config creates missing nested structures."""
        config = {}
        result = selftools._enforce_protected_config(config)
        self.assertTrue(result["signature"]["enabled"])
        self.assertEqual(result["signature"]["strategy"], "hash_chain")
        self.assertTrue(result["impact"]["enabled"])

    def test_enforce_protected_config_idempotent(self):
        """Enforcing on already-correct config is a no-op."""
        config = {
            "signature": {"enabled": True, "strategy": "hash_chain"},
            "impact": {"enabled": True},
        }
        result = selftools._enforce_protected_config(config)
        self.assertEqual(result, config)

    def test_deep_merge_skips_protected_keys(self):
        """_deep_merge_dict skips protected keys from override."""
        base = {
            "signature": {"enabled": True, "strategy": "hash_chain"},
            "impact": {"enabled": True},
        }
        override = {
            "signature": {"enabled": False, "strategy": "disabled"},
            "impact": {"enabled": False},
            "query": {"default_limit": 50},
        }
        result = selftools._deep_merge_dict(base, override)
        # Protected keys must NOT be overridden
        self.assertTrue(result["signature"]["enabled"])
        self.assertEqual(result["signature"]["strategy"], "hash_chain")
        self.assertTrue(result["impact"]["enabled"])
        # Non-protected key IS overridden
        self.assertEqual(result["query"]["default_limit"], 50)

    def test_deep_merge_preserves_non_protected(self):
        """Non-protected config values are merged normally."""
        base = {"query": {"enabled_modules": ["identity"], "default_limit": 10}}
        override = {"query": {"default_limit": 20, "extra_key": "val"}}
        result = selftools._deep_merge_dict(base, override)
        self.assertEqual(result["query"]["default_limit"], 20)
        self.assertEqual(result["query"]["extra_key"], "val")
        self.assertEqual(result["query"]["enabled_modules"], ["identity"])


class TestProtectedConfigWithLoadAidsConfig(TempDataMixin, unittest.TestCase):
    def test_load_config_enforces_protected(self):
        """load_aids_config always enforces protected keys."""
        config_path = selftools.data_dir() / "config.json"
        selftools.write_json_atomic(config_path, {
            "signature": {"enabled": False, "strategy": "disabled"},
            "impact": {"enabled": False},
            "query": {"default_limit": 99},
        })
        config = selftools.load_aids_config()
        self.assertTrue(config["signature"]["enabled"])
        self.assertEqual(config["signature"]["strategy"], "hash_chain")
        self.assertTrue(config["impact"]["enabled"])
        self.assertEqual(config["query"]["default_limit"], 99)

    def test_load_config_empty_file(self):
        """load_aids_config with missing/empty config returns defaults + protected."""
        config = selftools.load_aids_config()
        self.assertTrue(config["signature"]["enabled"])
        self.assertEqual(config["signature"]["strategy"], "hash_chain")
        self.assertTrue(config["impact"]["enabled"])


# ─── infer_runtime ───


class TestInferRuntime(TempDataMixin, unittest.TestCase):
    def test_env_var_takes_priority(self):
        """AIDS_RUNTIME env var overrides transcript_path heuristics."""
        with patch.dict(os.environ, {"AIDS_RUNTIME": "claude"}):
            result = selftools.infer_runtime({"transcript_path": "/home/.codex/sessions/1"})
        self.assertEqual(result, "claude")

    def test_codex_transcript_path(self):
        """transcript_path containing '.codex' returns 'codex'."""
        self._clear_runtime_env()
        result = selftools.infer_runtime({"transcript_path": "/home/user/.codex/sessions/abc"})
        self.assertEqual(result, "codex")

    def test_claude_transcript_path(self):
        """transcript_path containing '.claude' returns 'claude'."""
        self._clear_runtime_env()
        result = selftools.infer_runtime({"transcript_path": "/home/user/.claude/projects/xyz"})
        self.assertEqual(result, "claude")

    def test_claude_env_file(self):
        """CLAUDE_ENV_FILE set → returns 'claude'."""
        self._clear_runtime_env()
        with patch.dict(os.environ, {"CLAUDE_ENV_FILE": "/tmp/env"}, clear=False):
            # Remove any AIDS_RUNTIME that might be set
            os.environ.pop("AIDS_RUNTIME", None)
            os.environ.pop("AID_RUNTIME", None)
            result = selftools.infer_runtime({})
        self.assertEqual(result, "claude")

    def test_unknown_when_no_clues(self):
        """No env vars, no transcript_path, no CLAUDE_ENV_FILE → 'unknown'."""
        self._clear_runtime_env()
        with patch.dict(os.environ, {}, clear=False):
            for key in ["AIDS_RUNTIME", "AID_RUNTIME", "SELFTOOLS_RUNTIME", "ZHUYI_RUNTIME", "CLAUDE_ENV_FILE"]:
                os.environ.pop(key, None)
            result = selftools.infer_runtime({})
        self.assertEqual(result, "unknown")

    def test_empty_transcript_path_falls_through(self):
        """Empty transcript_path does not match .codex or .claude."""
        self._clear_runtime_env()
        with patch.dict(os.environ, {}, clear=False):
            for key in ["AIDS_RUNTIME", "AID_RUNTIME", "SELFTOOLS_RUNTIME", "ZHUYI_RUNTIME", "CLAUDE_ENV_FILE"]:
                os.environ.pop(key, None)
            result = selftools.infer_runtime({"transcript_path": ""})
        self.assertEqual(result, "unknown")

    def test_priority_env_over_transcript(self):
        """AIDS_RUNTIME='codex' overrides transcript_path with '.claude'."""
        with patch.dict(os.environ, {"AIDS_RUNTIME": "codex"}):
            result = selftools.infer_runtime({"transcript_path": "/home/.claude/proj"})
        self.assertEqual(result, "codex")

    def _clear_runtime_env(self):
        """Remove runtime-related env vars for clean test."""
        for key in ["AIDS_RUNTIME", "AID_RUNTIME", "SELFTOOLS_RUNTIME", "ZHUYI_RUNTIME", "CLAUDE_ENV_FILE"]:
            os.environ.pop(key, None)


# ─── infer_actor_type ───


class TestInferActorType(TempDataMixin, unittest.TestCase):
    def test_claude_is_agent(self):
        self.assertEqual(selftools.infer_actor_type("claude"), "agent")

    def test_codex_is_agent(self):
        self.assertEqual(selftools.infer_actor_type("codex"), "agent")

    def test_bash_with_session_id_is_human(self):
        with patch.dict(os.environ, {"AIDS_SESSION_ID": "sess-1"}, clear=False):
            # Clear actor_type env so it doesn't override
            for key in ["AIDS_ACTOR_TYPE", "AID_ACTOR_TYPE", "SELFTOOLS_ACTOR_TYPE", "ZHUYI_ACTOR_TYPE"]:
                os.environ.pop(key, None)
            result = selftools.infer_actor_type("bash")
        self.assertEqual(result, "human")

    def test_bash_without_session_id(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ["AIDS_SESSION_ID", "AID_SESSION_ID", "SESSION_ID", "SELFTOOLS_SESSION_ID", "ZHUYI_SESSION_ID"]:
                os.environ.pop(key, None)
            for key in ["AIDS_ACTOR_TYPE", "AID_ACTOR_TYPE", "SELFTOOLS_ACTOR_TYPE", "ZHUYI_ACTOR_TYPE"]:
                os.environ.pop(key, None)
            result = selftools.infer_actor_type("bash")
        self.assertEqual(result, "bash")

    def test_unknown_runtime_is_unknown_actor(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ["AIDS_ACTOR_TYPE", "AID_ACTOR_TYPE", "SELFTOOLS_ACTOR_TYPE", "ZHUYI_ACTOR_TYPE"]:
                os.environ.pop(key, None)
            result = selftools.infer_actor_type("unknown")
        self.assertEqual(result, "unknown")

    def test_env_var_overrides(self):
        with patch.dict(os.environ, {"AIDS_ACTOR_TYPE": "custom"}):
            result = selftools.infer_actor_type("claude")
        self.assertEqual(result, "custom")


# ─── agent_id backfill in register_session ───


class TestAgentIdBackfill(TempDataMixin, unittest.TestCase):
    def test_fresh_session_gets_agent_id(self):
        """New session registration computes agent_id."""
        os.environ["AIDS_SESSION_ID"] = "sess-backfill-1"
        os.environ["AIDS_DISPLAY_NAME"] = "BackfillBot"
        os.environ["AIDS_ROLE"] = "implementer"
        try:
            record = selftools.register_session({"session_id": "sess-backfill-1", "cwd": "/tmp"}, source="test")
            self.assertTrue(record["agent_id"].startswith("agent-"))
            expected = selftools.compute_agent_id("BackfillBot", "implementer")
            self.assertEqual(record["agent_id"], expected)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)

    def test_reregistration_preserves_existing_agent_id(self):
        """Re-registration preserves existing agent_id, does not recompute."""
        os.environ["AIDS_SESSION_ID"] = "sess-preserve"
        os.environ["AIDS_DISPLAY_NAME"] = "PreserveBot"
        os.environ["AIDS_ROLE"] = "implementer"
        try:
            # First registration
            r1 = selftools.register_session({"session_id": "sess-preserve", "cwd": "/tmp"}, source="test")
            original_aid = r1["agent_id"]

            # Change display name and re-register
            os.environ["AIDS_DISPLAY_NAME"] = "NewNameBot"
            r2 = selftools.register_session({"session_id": "sess-preserve", "cwd": "/tmp"}, source="test")

            # agent_id should NOT change — it was already set
            self.assertEqual(r2["agent_id"], original_aid)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)

    def test_old_session_without_agent_id_gets_backfilled(self):
        """Legacy session file without agent_id gets it backfilled on next registration."""
        # Write a legacy session without agent_id
        legacy = {
            "session_id": "sess-legacy",
            "runtime": "claude",
            "role": "implementer",
            "display_name": "LegacyBot",
            "status": "active",
        }
        selftools.write_json_atomic(selftools.session_path("sess-legacy"), legacy)

        os.environ["AIDS_SESSION_ID"] = "sess-legacy"
        os.environ["AIDS_DISPLAY_NAME"] = "LegacyBot"
        os.environ["AIDS_ROLE"] = "implementer"
        try:
            record = selftools.register_session({"session_id": "sess-legacy", "cwd": "/tmp"}, source="test")
            # agent_id should now be present and match expected
            self.assertIn("agent_id", record)
            self.assertTrue(record["agent_id"].startswith("agent-"))
            expected = selftools.compute_agent_id("LegacyBot", "implementer")
            self.assertEqual(record["agent_id"], expected)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)

    def test_agent_id_stable_across_multiple_sessions(self):
        """Same (name, role, team) → same agent_id across different session IDs."""
        os.environ["AIDS_ROLE"] = "architect"
        try:
            for i in range(3):
                sid = f"sess-stable-{i}"
                os.environ["AIDS_SESSION_ID"] = sid
                os.environ["AIDS_DISPLAY_NAME"] = "StableBot"
                record = selftools.register_session({"session_id": sid, "cwd": "/tmp"}, source="test")
                expected = selftools.compute_agent_id("StableBot", "architect")
                self.assertEqual(record["agent_id"], expected)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)

    def test_different_agents_different_ids(self):
        """Different display names produce different agent_ids."""
        ids = set()
        for name in ["Alice", "Bob", "Charlie"]:
            sid = f"sess-diff-{name}"
            os.environ["AIDS_SESSION_ID"] = sid
            os.environ["AIDS_DISPLAY_NAME"] = name
            os.environ["AIDS_ROLE"] = "implementer"
            try:
                record = selftools.register_session({"session_id": sid, "cwd": "/tmp"}, source="test")
                ids.add(record["agent_id"])
            finally:
                os.environ.pop("AIDS_SESSION_ID", None)
                os.environ.pop("AIDS_DISPLAY_NAME", None)
                os.environ.pop("AIDS_ROLE", None)
        self.assertEqual(len(ids), 3, "Each agent should have a unique agent_id")


# ─── Stats with agent_id data ───


class TestStatsAgentAggregation(TempDataMixin, unittest.TestCase):
    def _seed_multi_agent(self):
        """Seed sessions with agent_ids and traces for stats testing."""
        dd = selftools.data_dir()

        agents = [
            ("Alpha", "implementer", "claude", "team-1"),
            ("Alpha", "implementer", "claude", "team-1"),  # same agent, second session
            ("Beta", "reviewer", "codex", "team-1"),
            ("Gamma", "master", "claude", "team-2"),
        ]
        for i, (name, role, runtime, team) in enumerate(agents):
            sid = f"stats-agent-{i}"
            aid = selftools.compute_agent_id(name, role, team)
            record = {
                "session_id": sid,
                "runtime": runtime,
                "role": role,
                "status": "active",
                "display_name": name,
                "agent_id": aid,
                "team_id": team,
                "started_at": selftools.now_ms(),
                "started_iso": selftools.iso_now(),
            }
            selftools.write_json_atomic(dd / "sessions" / f"{sid}.json", record)

        # Traces linked to sessions
        today_file = selftools.traces_file_for_today()
        trace_data = [
            ("stats-agent-0", "claude", "modify"),
            ("stats-agent-0", "claude", "read"),
            ("stats-agent-1", "claude", "create"),     # same agent as agent-0
            ("stats-agent-2", "codex", "modify"),
            ("stats-agent-3", "claude", "execute"),
        ]
        for i, (sid, runtime, op) in enumerate(trace_data):
            trace = {
                "trace_id": f"tr_agg_{i}",
                "session_id": sid,
                "tool": "Write" if op != "execute" else "Bash",
                "resource_path": f"/tmp/agg_{i}.py",
                "operation": op,
                "intent": "aggregation test",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
                "runtime": runtime,
                "actor_type": "agent",
            }
            selftools.append_jsonl(today_file, trace)

    def test_stats_json_includes_all_sessions(self):
        """Stats JSON counts all sessions including multi-session agents."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"]["total"], 4)

    def test_stats_by_runtime_counts(self):
        """Stats groups traces by runtime correctly."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())
        # 4 claude traces + 1 codex trace
        self.assertEqual(result["traces"]["total"], 5)
        self.assertEqual(result["traces"]["by_runtime"]["claude"], 4)
        self.assertEqual(result["traces"]["by_runtime"]["codex"], 1)

    def test_stats_by_role_from_sessions(self):
        """Stats groups sessions by role correctly."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())
        by_role = result["sessions"]["by_role"]
        self.assertEqual(by_role["implementer"], 2)  # agent-0 and agent-1
        self.assertEqual(by_role["reviewer"], 1)
        self.assertEqual(by_role["master"], 1)

    def test_stats_top_sessions_enriched(self):
        """Top sessions include display_name and role."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())
        top = result["top_sessions"]
        self.assertGreater(len(top), 0)
        for s in top:
            self.assertIn("session_id", s)
            self.assertIn("ops", s)
            self.assertIn("role", s)
            self.assertIn("runtime", s)

    def test_stats_unknown_runtime_traces(self):
        """Traces with runtime='unknown' are counted correctly."""
        today_file = selftools.traces_file_for_today()
        trace = {
            "trace_id": "tr_unknown_rt",
            "session_id": "sess-unknown",
            "tool": "Bash",
            "resource_path": "/tmp/unknown_rt.py",
            "operation": "execute",
            "intent": "unknown runtime test",
            "timestamp": selftools.now_ms(),
            "timestamp_iso": selftools.iso_now(),
            "runtime": "unknown",
            "actor_type": "agent",
        }
        selftools.append_jsonl(today_file, trace)

        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())
        self.assertGreaterEqual(result["traces"]["by_runtime"].get("unknown", 0), 1)

    def test_stats_by_agent_manual_aggregation(self):
        """Verify agent_id-based aggregation by manual grouping of session data."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())

        # Manually aggregate top_sessions by agent_id via session lookup
        dd = selftools.data_dir()
        agent_trace_counts = {}
        for f in (dd / "sessions").glob("*.json"):
            rec = selftools.read_json(f, {}) or {}
            aid = rec.get("agent_id", "unknown")
            agent_trace_counts[aid] = agent_trace_counts.get(aid, 0)

        # Alpha has 2 sessions, Beta 1, Gamma 1
        alpha_id = selftools.compute_agent_id("Alpha", "implementer", "team-1")
        beta_id = selftools.compute_agent_id("Beta", "reviewer", "team-1")
        gamma_id = selftools.compute_agent_id("Gamma", "master", "team-2")

        # Verify each agent has an entry
        self.assertIn(alpha_id, agent_trace_counts)
        self.assertIn(beta_id, agent_trace_counts)
        self.assertIn(gamma_id, agent_trace_counts)

        # Alpha should be the same agent_id for both sessions
        sess0 = selftools.load_session("stats-agent-0")
        sess1 = selftools.load_session("stats-agent-1")
        self.assertEqual(sess0["agent_id"], sess1["agent_id"])
        self.assertEqual(sess0["agent_id"], alpha_id)

    def test_stats_resources_count(self):
        """Stats counts unique resources correctly."""
        self._seed_multi_agent()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            selftools.cmd_stats(args)
        result = json.loads(captured.getvalue())
        self.assertGreaterEqual(result["resources"]["unique"], 5)
        self.assertGreater(len(result["resources"]["top"]), 0)


# ─── register_session runtime backfill ───


class TestRegisterSessionRuntimeBackfill(TempDataMixin, unittest.TestCase):
    def test_unknown_runtime_preserves_old(self):
        """When infer_runtime returns 'unknown', old runtime is preserved."""
        # Create session with known runtime
        os.environ["AIDS_SESSION_ID"] = "sess-rt-back"
        os.environ["AIDS_DISPLAY_NAME"] = "RtBot"
        os.environ["AIDS_ROLE"] = "implementer"
        os.environ["AIDS_RUNTIME"] = "claude"
        try:
            r1 = selftools.register_session({"session_id": "sess-rt-back", "cwd": "/tmp"}, source="test")
            self.assertEqual(r1["runtime"], "claude")

            # Re-register without runtime info — should keep claude
            os.environ.pop("AIDS_RUNTIME", None)
            for key in ["AIDS_RUNTIME", "AID_RUNTIME", "SELFTOOLS_RUNTIME", "ZHUYI_RUNTIME", "CLAUDE_ENV_FILE"]:
                os.environ.pop(key, None)
            r2 = selftools.register_session({"session_id": "sess-rt-back", "cwd": "/tmp"}, source="test")
            self.assertEqual(r2["runtime"], "claude", "Runtime should be preserved from previous registration")
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)


# ─── FileLock TTL + timeout ───


class TestFileLockTTL(TempDataMixin, unittest.TestCase):
    def test_default_ttl_is_30(self):
        """FileLock.DEFAULT_TTL should be 30 seconds."""
        self.assertEqual(selftools.FileLock.DEFAULT_TTL, 30)

    def test_expired_lock_is_broken(self):
        """A lock file with an expired timestamp should be broken."""
        lock_path = selftools.data_dir() / "locks" / "test_ttl.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a lock with an old timestamp (expired)
        old_ts = selftools.now_ms() - 60_000  # 60 seconds ago
        lock_path.write_text(
            json.dumps({"pid": 999999, "ts": old_ts}) + "\n",
            encoding="utf-8",
        )
        lock = selftools.FileLock(lock_path, timeout=1.0, ttl=30.0)
        self.assertTrue(lock._break_stale_lock())

    def test_is_lock_expired_true_for_old_lock(self):
        """_is_lock_expired returns True for locks older than TTL."""
        lock_path = selftools.data_dir() / "locks" / "test_expired.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        old_ts = selftools.now_ms() - 120_000  # 2 minutes ago
        lock_path.write_text(
            json.dumps({"pid": 999999, "ts": old_ts}) + "\n",
            encoding="utf-8",
        )
        lock = selftools.FileLock(lock_path, timeout=1.0, ttl=30.0)
        self.assertTrue(lock._is_lock_expired())

    def test_is_lock_expired_false_for_recent_lock(self):
        """_is_lock_expired returns False for locks within TTL."""
        lock_path = selftools.data_dir() / "locks" / "test_recent.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        recent_ts = selftools.now_ms() - 1_000  # 1 second ago
        lock_path.write_text(
            json.dumps({"pid": 999999, "ts": recent_ts}) + "\n",
            encoding="utf-8",
        )
        lock = selftools.FileLock(lock_path, timeout=1.0, ttl=30.0)
        self.assertFalse(lock._is_lock_expired())

    def test_context_manager_acquires_lock(self):
        """Context manager successfully acquires and releases a lock."""
        lock_path = selftools.data_dir() / "locks" / "test_ctx.lock"
        lock = selftools.FileLock(lock_path, timeout=2.0)
        with lock:
            self.assertTrue(lock._owns_lock)
        self.assertFalse(lock._owns_lock)

    def test_context_manager_timeout_on_held_lock(self):
        """Context manager raises TimeoutError when lock is held by live process."""
        import fcntl as _fcntl
        lock_path = selftools.data_dir() / "locks" / "test_timeout.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Simulate a live holder: open and flock the file
        holder_fd = open(lock_path, "a+", encoding="utf-8")
        _fcntl.flock(holder_fd.fileno(), _fcntl.LOCK_EX)
        holder_fd.write(json.dumps({"pid": os.getpid(), "ts": selftools.now_ms()}) + "\n")
        holder_fd.flush()
        try:
            lock = selftools.FileLock(lock_path, timeout=0.3, ttl=60.0)
            with self.assertRaises(TimeoutError):
                with lock:
                    pass
        finally:
            _fcntl.flock(holder_fd.fileno(), _fcntl.LOCK_UN)
            holder_fd.close()

    def test_stale_lock_class_constant_preserved(self):
        """STALE_SECONDS should remain 300 for clean_all_stale_locks."""
        self.assertEqual(selftools.FileLock.STALE_SECONDS, 300)

    def test_acquire_skips_ttl_check(self):
        """acquire path (check_ttl=False) must NOT break a lock that is TTL-expired
        but held by a live PID.  Only dead-PID locks should be broken."""
        import fcntl as _fcntl
        lock_path = selftools.data_dir() / "locks" / "test_acquire_skip_ttl.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Create a TTL-expired lock held by current (live) process
        old_ts = selftools.now_ms() - 60_000  # 60s ago → TTL expired
        holder_fd = open(lock_path, "a+", encoding="utf-8")
        _fcntl.flock(holder_fd.fileno(), _fcntl.LOCK_EX)
        holder_fd.write(json.dumps({"pid": os.getpid(), "ts": old_ts}) + "\n")
        holder_fd.flush()
        try:
            lock = selftools.FileLock(lock_path, timeout=0.3, ttl=30.0)
            # check_ttl=False → should NOT break the lock (holder is alive)
            self.assertFalse(lock._break_stale_lock(check_ttl=False))
            # check_ttl=True (default) → SHOULD break the lock (TTL expired)
            self.assertTrue(lock._break_stale_lock())
        finally:
            _fcntl.flock(holder_fd.fileno(), _fcntl.LOCK_UN)
            holder_fd.close()

    def test_clean_locks_checks_ttl(self):
        """clean_all_stale_locks uses mtime-based cleanup (STALE_SECONDS),
        independent of _break_stale_lock TTL logic."""
        import time as _time
        locks_dir = selftools.data_dir() / "locks"
        locks_dir.mkdir(parents=True, exist_ok=True)
        # Create a stale lock file (old mtime)
        stale_lock = locks_dir / "stale_clean.lock"
        stale_lock.write_text('{"pid": 999999}', encoding="utf-8")
        # Backdate mtime beyond STALE_SECONDS
        old_time = _time.time() - selftools.FileLock.STALE_SECONDS - 60
        import os as _os
        _os.utime(stale_lock, (old_time, old_time))
        selftools.clean_all_stale_locks()
        self.assertFalse(stale_lock.exists())


# ─── commit-stamp ───


class TestCmdCommitStamp(TempDataMixin, unittest.TestCase):
    def _seed_session_and_traces(self, session_id="stamp-s1"):
        """Seed a session + traces for commit-stamp testing."""
        dd = selftools.data_dir()
        session = {
            "session_id": session_id,
            "runtime": "claude",
            "role": "implementer",
            "status": "active",
            "display_name": "StampAgent",
        }
        selftools.write_json_atomic(dd / "sessions" / f"{session_id}.json", session)
        # Write traces
        today_file = selftools.traces_file_for_today()
        for i in range(3):
            trace = {
                "trace_id": f"tr_stamp_{i}",
                "session_id": session_id,
                "tool": "Write",
                "resource_path": f"/tmp/file_{i}.py",
                "operation": "modify",
                "intent": "test stamp",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
                "runtime": "claude",
                "actor_type": "agent",
                "chain_hash": f"hash_{i}",
            }
            selftools.append_jsonl(today_file, trace)

    def test_commit_stamp_human_output(self):
        """commit-stamp prints Co-Authored-By trailer in human mode."""
        self._seed_session_and_traces("stamp-human")
        os.environ["AIDS_SESSION_ID"] = "stamp-human"
        os.environ["AIDS_DISPLAY_NAME"] = "StampBot"
        os.environ["AIDS_ROLE"] = "implementer"
        os.environ["AIDS_RUNTIME"] = "claude"
        try:
            args = selftools.build_parser().parse_args(["commit-stamp"])
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = selftools.cmd_commit_stamp(args)
            self.assertEqual(rc, 0)
            output = captured.getvalue()
            self.assertIn("Co-Authored-By:", output)
            self.assertIn("StampBot", output)
            self.assertIn("AIDS-Trace-Summary:", output)
            self.assertIn("AIDS-Last-Trace:", output)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)
            os.environ.pop("AIDS_RUNTIME", None)

    def test_commit_stamp_json_output(self):
        """commit-stamp --json returns structured JSON with trace summary."""
        self._seed_session_and_traces("stamp-json")
        os.environ["AIDS_SESSION_ID"] = "stamp-json"
        os.environ["AIDS_DISPLAY_NAME"] = "JsonBot"
        os.environ["AIDS_ROLE"] = "implementer"
        os.environ["AIDS_RUNTIME"] = "claude"
        try:
            args = selftools.build_parser().parse_args(["commit-stamp", "--json"])
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = selftools.cmd_commit_stamp(args)
            self.assertEqual(rc, 0)
            result = json.loads(captured.getvalue())
            self.assertIn("trailer", result)
            self.assertIn("JsonBot", result["trailer"])
            self.assertEqual(result["session_id"], "stamp-json")
            self.assertEqual(result["trace_summary"]["trace_count"], 3)
            self.assertEqual(result["trace_summary"]["unique_resources"], 3)
            self.assertTrue(result["trace_summary"]["chain_signed"])
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)
            os.environ.pop("AIDS_RUNTIME", None)

    def test_commit_stamp_no_traces(self):
        """commit-stamp works even with no traces (just shows trailer)."""
        os.environ["AIDS_SESSION_ID"] = "stamp-empty"
        os.environ["AIDS_DISPLAY_NAME"] = "EmptyBot"
        os.environ["AIDS_ROLE"] = "tester"
        os.environ["AIDS_RUNTIME"] = "bash"
        try:
            args = selftools.build_parser().parse_args(["commit-stamp"])
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = selftools.cmd_commit_stamp(args)
            self.assertEqual(rc, 0)
            output = captured.getvalue()
            self.assertIn("Co-Authored-By:", output)
            self.assertIn("EmptyBot", output)
            self.assertNotIn("AIDS-Trace-Summary:", output)
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)
            os.environ.pop("AIDS_RUNTIME", None)

    def test_commit_stamp_json_no_traces(self):
        """commit-stamp --json with no traces shows zero counts."""
        os.environ["AIDS_SESSION_ID"] = "stamp-nodata"
        os.environ["AIDS_DISPLAY_NAME"] = "NoDataBot"
        os.environ["AIDS_ROLE"] = "tester"
        os.environ["AIDS_RUNTIME"] = "bash"
        try:
            args = selftools.build_parser().parse_args(["commit-stamp", "--json"])
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = selftools.cmd_commit_stamp(args)
            self.assertEqual(rc, 0)
            result = json.loads(captured.getvalue())
            self.assertEqual(result["trace_summary"]["trace_count"], 0)
            self.assertEqual(result["trace_summary"]["unique_resources"], 0)
            self.assertFalse(result["trace_summary"]["chain_signed"])
        finally:
            os.environ.pop("AIDS_SESSION_ID", None)
            os.environ.pop("AIDS_DISPLAY_NAME", None)
            os.environ.pop("AIDS_ROLE", None)
            os.environ.pop("AIDS_RUNTIME", None)


class TestStatsByAgent(TempDataMixin, unittest.TestCase):
    def _seed(self):
        dd = selftools.data_dir()
        for i, (name, role, rt, team) in enumerate([
            ("Bot-A", "implementer", "claude", "team-1"),
            ("Bot-A", "implementer", "claude", "team-1"),
            ("Bot-B", "reviewer", "codex", "team-1"),
        ]):
            sid = f"sa-sess-{i}"
            record = {
                "session_id": sid,
                "runtime": rt,
                "role": role,
                "status": "active",
                "display_name": name,
                "team_id": team,
                "started_at": selftools.now_ms(),
                "started_iso": selftools.iso_now(),
            }
            selftools.write_json_atomic(dd / "sessions" / f"{sid}.json", record)
        today_file = selftools.traces_file_for_today()
        for i in range(5):
            trace = {
                "trace_id": f"tr_sa_{i}",
                "session_id": f"sa-sess-{i % 3}",
                "operation": "read" if i % 2 == 0 else "modify",
                "resource_path": f"/tmp/f{i}.py",
                "runtime": "claude",
                "timestamp": selftools.now_ms(),
                "timestamp_iso": selftools.iso_now(),
            }
            selftools.append_jsonl(today_file, trace)

    def test_stats_by_agent_json(self):
        self._seed()
        args = selftools.build_parser().parse_args(["stats", "--all", "--by-agent", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertIn("by_agent", result)
        self.assertIn("sessions", result["by_agent"])
        self.assertIn("traces", result["by_agent"])
        self.assertEqual(len(result["by_agent"]["sessions"]), 2)

    def test_stats_by_agent_human(self):
        self._seed()
        args = selftools.build_parser().parse_args(["stats", "--all", "--by-agent"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        self.assertIn("By agent:", captured.getvalue())

    def test_stats_without_by_agent_no_section(self):
        self._seed()
        args = selftools.build_parser().parse_args(["stats", "--all", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_stats(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertNotIn("by_agent", result)


class TestWhoisBackfillAgentId(TempDataMixin, unittest.TestCase):
    def test_whois_backfills_missing_agent_id(self):
        dd = selftools.data_dir()
        sid = "old-sess-no-aid"
        record = {
            "session_id": sid,
            "display_name": "LegacyBot",
            "role": "implementer",
            "team_id": "team-x",
            "runtime": "claude",
            "status": "active",
        }
        selftools.write_json_atomic(dd / "sessions" / f"{sid}.json", record)
        args = selftools.build_parser().parse_args(["whois", sid, "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_whois(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertTrue(result["agent_id"].startswith("agent-"))
        reloaded = selftools.read_json(dd / "sessions" / f"{sid}.json", {})
        self.assertEqual(reloaded["agent_id"], result["agent_id"])

    def test_whois_preserves_existing_agent_id(self):
        dd = selftools.data_dir()
        sid = "new-sess-has-aid"
        record = {
            "session_id": sid,
            "agent_id": "agent-original123",
            "display_name": "NewBot",
            "role": "implementer",
            "runtime": "codex",
            "status": "active",
        }
        selftools.write_json_atomic(dd / "sessions" / f"{sid}.json", record)
        args = selftools.build_parser().parse_args(["whois", sid, "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_whois(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["agent_id"], "agent-original123")


class TestListSessionsRuntimeInfer(TempDataMixin, unittest.TestCase):
    def test_infer_runtime_from_transcript_path(self):
        dd = selftools.data_dir()
        record = {
            "session_id": "rt-infer-1",
            "runtime": "unknown",
            "role": "implementer",
            "status": "active",
            "transcript_path": "/home/user/.claude/projects/abc/session.jsonl",
        }
        selftools.write_json_atomic(dd / "sessions" / "rt-infer-1.json", record)
        args = selftools.build_parser().parse_args(["list-sessions", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"][0]["runtime"], "claude")

    def test_infer_runtime_from_model(self):
        dd = selftools.data_dir()
        record = {
            "session_id": "rt-infer-2",
            "role": "implementer",
            "status": "active",
            "model": "claude-sonnet-4-6",
        }
        selftools.write_json_atomic(dd / "sessions" / "rt-infer-2.json", record)
        args = selftools.build_parser().parse_args(["list-sessions", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"][0]["runtime"], "claude")

    def test_infer_runtime_codex_from_transcript(self):
        dd = selftools.data_dir()
        record = {
            "session_id": "rt-infer-3",
            "runtime": "unknown",
            "role": "implementer",
            "status": "active",
            "transcript_path": "/home/user/.codex/sessions/abc.jsonl",
        }
        selftools.write_json_atomic(dd / "sessions" / "rt-infer-3.json", record)
        args = selftools.build_parser().parse_args(["list-sessions", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"][0]["runtime"], "codex")

    def test_known_runtime_unchanged(self):
        dd = selftools.data_dir()
        record = {
            "session_id": "rt-infer-4",
            "runtime": "bash",
            "role": "human",
            "status": "retired",
        }
        selftools.write_json_atomic(dd / "sessions" / "rt-infer-4.json", record)
        args = selftools.build_parser().parse_args(["list-sessions", "--json"])
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            rc = selftools.cmd_list_sessions(args)
        self.assertEqual(rc, 0)
        result = json.loads(captured.getvalue())
        self.assertEqual(result["sessions"][0]["runtime"], "bash")


if __name__ == "__main__":
    unittest.main()
