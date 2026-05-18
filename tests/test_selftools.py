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


class TestBuildParser(unittest.TestCase):
    def test_all_subcommands_registered(self):
        p = selftools.build_parser()
        # Parse each subcommand to verify it exists
        for cmd in ["stats", "export", "q", "query", "ask", "timeline", "doctor", "list-sessions", "who-touched", "op-chain", "rate", "heartbeat", "whois", "session-info", "retire-session", "register-session"]:
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


if __name__ == "__main__":
    unittest.main()
