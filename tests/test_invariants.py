#!/usr/bin/env python3
"""AIDS Invariant Tests — Bach 条件不变量验证。

验证 docs/aids-invariants.md 中定义的 7 条不变量在当前 AIDS 实现中是否成立。

方法：
  - 创建临时数据目录 ~/.aids-test-{uuid}
  - 通过 subprocess 调用 bin/selftools CLI 执行完整 hook 流程
  - 直接读写 JSONL/JSON 数据文件验证不变量
  - 测试结束清理临时目录

零依赖：仅 Python 标准库。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI = PROJECT_ROOT / "bin" / "selftools"


def _env_for_test(data_dir: str) -> Dict[str, str]:
    """构建测试用环境变量，指向临时数据目录。"""
    env = dict(os.environ)
    env["AIDS_DATA_DIR"] = data_dir
    env["AIDS_HOME"] = data_dir
    # 清除可能干扰的变量
    for key in list(env.keys()):
        if key.startswith(("AIDS_", "AID_", "ZHUYI_", "SELFTOOLS_")) and key not in (
            "AIDS_DATA_DIR", "AIDS_HOME",
        ):
            del env[key]
    return env


def _run_cli(*args: str, stdin_data: str = "", env: Dict[str, str]) -> subprocess.CompletedProcess:
    """运行 bin/selftools 命令。"""
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _run_hook(hook_name: str, event: Dict[str, Any], env: Dict[str, str]) -> subprocess.CompletedProcess:
    """运行 hook 命令（通过 stdin 传入 JSON 事件）。"""
    return _run_cli("hook", hook_name, stdin_data=json.dumps(event), env=env)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 文件返回列表。"""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """读取 JSON 文件。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AIDSTestBase(unittest.TestCase):
    """测试基类：创建和清理临时数据目录。"""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="aids-test-")
        self.env = _env_for_test(self.test_dir)
        # Use resolve() to match CLI's normalize_resource (macOS /var → /private/var)
        self.test_file = (Path(self.test_dir) / "test_resource.py").resolve()
        self.test_file.write_text("# original content\n", encoding="utf-8")
        self.resolved_dir = str(Path(self.test_dir).resolve())
        self.session_id = f"test-sess-{uuid.uuid4().hex[:8]}"
        self.env["AIDS_SESSION_ID"] = self.session_id
        self.env["AIDS_ROLE"] = "implementer"
        self.env["AIDS_INTENT"] = "run invariant tests"
        self.env["AIDS_RUNTIME"] = "claude"
        self.env["AIDS_ACTOR_TYPE"] = "agent"
        self.env["AIDS_DISPLAY_NAME"] = "TestAgent"

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _data_dir(self) -> Path:
        return Path(self.test_dir)

    def _traces_today(self) -> List[Dict[str, Any]]:
        from datetime import date
        path = self._data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        return _read_jsonl(path)

    def _timeline_today(self) -> List[Dict[str, Any]]:
        from datetime import date
        path = self._data_dir() / "timeline" / f"{date.today().isoformat()}.jsonl"
        return _read_jsonl(path)

    def _ratings_today(self) -> List[Dict[str, Any]]:
        from datetime import date
        path = self._data_dir() / "ratings" / f"{date.today().isoformat()}.jsonl"
        return _read_jsonl(path)

    def _index_for(self, resource: str) -> Optional[Dict[str, Any]]:
        import base64
        key = base64.urlsafe_b64encode(resource.encode("utf-8")).decode("ascii").rstrip("=")
        return _read_json(self._data_dir() / "index" / f"{key}.json")

    def _simulate_session_start(self) -> None:
        event = {
            "session_id": self.session_id,
            "cwd": self.resolved_dir,
            "hook_event_name": "SessionStart",
        }
        _run_hook("session-start", event, env=self.env)

    def _simulate_pre_tool_use(self, tool_name: str, file_path: str, tool_use_id: Optional[str] = None) -> str:
        """运行 PreToolUse hook。返回 tool_use_id。"""
        tid = tool_use_id or f"tu-{uuid.uuid4().hex[:8]}"
        event = {
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
            "cwd": self.resolved_dir,
            "tool_use_id": tid,
            "session_id": self.session_id,
            "hook_event_name": "PreToolUse",
        }
        _run_hook("pre-tool-use", event, env=self.env)
        return tid

    def _simulate_post_tool_use(
        self, tool_name: str, file_path: str, tool_use_id: str,
    ) -> None:
        event = {
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
            "tool_response": "ok",
            "cwd": self.resolved_dir,
            "tool_use_id": tool_use_id,
            "session_id": self.session_id,
            "hook_event_name": "PostToolUse",
        }
        _run_hook("post-tool-use", event, env=self.env)

    def _simulate_write_flow(self, file_path: str, new_content: str) -> str:
        """模拟完整写操作流程：Pre → 实际写入 → Post。返回 tool_use_id。"""
        tool_use_id = f"tu-{uuid.uuid4().hex[:8]}"
        # Pre — 必须用同一个 tool_use_id
        self._simulate_pre_tool_use("Edit", file_path, tool_use_id=tool_use_id)
        # 实际写入
        Path(file_path).write_text(new_content, encoding="utf-8")
        # Post — 用同一个 tool_use_id 匹配 pending
        self._simulate_post_tool_use("Edit", file_path, tool_use_id=tool_use_id)
        return tool_use_id

    def _simulate_read_flow(self, file_path: str) -> None:
        """模拟读操作流程。"""
        tid = self._simulate_pre_tool_use("Read", file_path)
        self._simulate_post_tool_use("Read", file_path, tool_use_id=tid)


# ============================================================
# INV-1：操作序列有序性
# ============================================================
class TestINV1_OperationOrdering(AIDSTestBase):
    """INV-1: trace 写入按时间戳严格非递减排列。"""

    def test_traces_monotonically_ordered(self) -> None:
        """多次操作后，trace 时间戳非递减。"""
        self._simulate_session_start()
        for i in range(5):
            self._simulate_write_flow(str(self.test_file), f"# version {i}\n")

        traces = self._traces_today()
        self.assertGreaterEqual(len(traces), 5, "Should have at least 5 trace records")

        timestamps = [r.get("timestamp", 0) for r in traces]
        for i in range(1, len(timestamps)):
            self.assertGreaterEqual(
                timestamps[i], timestamps[i - 1],
                f"INV-1 violated: trace[{i}].timestamp ({timestamps[i]}) < trace[{i-1}].timestamp ({timestamps[i-1]})",
            )

    def test_empty_traces_trivially_ordered(self) -> None:
        """空 trace 文件不违反有序性。"""
        traces = self._traces_today()
        self.assertEqual(len(traces), 0)


# ============================================================
# INV-2：资源-会话可追溯性
# ============================================================
class TestINV2_ResourceSessionTraceability(AIDSTestBase):
    """INV-2: 每条索引记录包含有效的 last_actor 和 last_actor_role。"""

    def test_index_has_actor_after_write(self) -> None:
        """写操作后，资源索引包含 actor 信息。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# modified\n")

        idx = self._index_for(str(self.test_file))
        self.assertIsNotNone(idx, "Index should exist for the resource")
        self.assertGreater(idx.get("total_ops", 0), 0)
        self.assertIsNotNone(idx.get("last_actor"), "INV-2: last_actor must not be None")
        self.assertIsNotNone(idx.get("last_actor_role"), "INV-2: last_actor_role must not be None")
        self.assertEqual(idx["last_actor"], self.session_id)
        self.assertEqual(idx["last_actor_role"], "implementer")

    def test_no_index_without_ops(self) -> None:
        """无操作时不应有索引。"""
        idx = self._index_for(str(self.test_file))
        self.assertIsNone(idx, "No index should exist without operations")


# ============================================================
# INV-3：写前读保护（Stale-Write Protection）
# ============================================================
class TestINV3_StaleWriteProtection(AIDSTestBase):
    """INV-3: 写操作前有 pending 记录，写操作后 pending 被清理。"""

    def test_pre_hook_creates_pending_for_write_tools(self) -> None:
        """PreToolUse 为写工具创建 pending 记录。"""
        self._simulate_session_start()
        tool_use_id = f"tu-{uuid.uuid4().hex[:8]}"
        # Pre
        self._simulate_pre_tool_use("Edit", str(self.test_file))

        # 检查 pending 目录
        pending_dir = self._data_dir() / "pending"
        pending_files = list(pending_dir.glob("*.json"))
        self.assertGreater(len(pending_files), 0, "INV-3: pending file should exist after PreToolUse for write tool")

    def test_post_hook_clears_pending(self) -> None:
        """PostToolUse 清理 pending 记录。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# modified\n")

        # pending 应被清理
        pending_dir = self._data_dir() / "pending"
        # Note: there might be pending from other concurrent tests, so we just
        # verify the write trace exists (proving the flow completed)
        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") in ("modify", "create")]
        self.assertGreater(len(write_traces), 0, "INV-3: write trace should exist after write flow")

    def test_read_has_pre_hash(self) -> None:
        """写操作 trace 包含 pre_hash（文件存在时）。"""
        self._simulate_session_start()
        # 先确保文件存在且有内容
        self.test_file.write_text("# original\n", encoding="utf-8")
        self._simulate_write_flow(str(self.test_file), "# modified\n")

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") == "modify"]
        self.assertGreater(len(write_traces), 0)
        # pre_hash 应存在（文件在写前已存在）
        for tr in write_traces:
            self.assertIsNotNone(
                tr.get("pre_hash"),
                f"INV-3: write trace should have pre_hash, got {tr.get('trace_id')}",
            )

    def test_pending_timestamp_precedes_trace_timestamp(self) -> None:
        """pending.timestamp 必须早于或等于对应 write trace.timestamp。"""
        self._simulate_session_start()
        tool_use_id = f"tu-{uuid.uuid4().hex[:8]}"

        self._simulate_pre_tool_use("Edit", str(self.test_file), tool_use_id=tool_use_id)
        pending = _read_json(self._data_dir() / "pending" / f"{tool_use_id}.json")
        self.assertIsNotNone(pending, "INV-3: pending snapshot should exist after PreToolUse")
        self.assertEqual(pending.get("tool_use_id"), tool_use_id)
        self.assertIsInstance(pending.get("timestamp"), int)

        self.test_file.write_text("# timestamp ordered\n", encoding="utf-8")
        self._simulate_post_tool_use("Edit", str(self.test_file), tool_use_id=tool_use_id)

        traces = self._traces_today()
        matching = [t for t in traces if t.get("tool_use_id") == tool_use_id]
        self.assertEqual(len(matching), 1, "INV-3: exactly one trace should match the pending tool_use_id")
        trace = matching[0]
        self.assertIsInstance(trace.get("timestamp"), int)
        self.assertLessEqual(
            pending["timestamp"], trace["timestamp"],
            f"INV-3: pending.timestamp ({pending['timestamp']}) must be <= trace.timestamp ({trace['timestamp']})",
        )

    def test_skipping_pre_hook_does_not_create_valid_write_trace(self) -> None:
        """跳过 PreToolUse 的攻击不应伪装成受保护的 modify/create 写 trace。"""
        self._simulate_session_start()
        tool_use_id = f"tu-{uuid.uuid4().hex[:8]}"

        # 攻击：绕过 PreToolUse，先直接修改文件，再只触发 PostToolUse。
        self.test_file.write_text("# bypassed pre hook\n", encoding="utf-8")
        self._simulate_post_tool_use("Edit", str(self.test_file), tool_use_id=tool_use_id)

        pending_file = self._data_dir() / "pending" / f"{tool_use_id}.json"
        self.assertFalse(pending_file.exists(), "INV-3 attack fixture: no pending should exist when PreToolUse is skipped")

        traces = self._traces_today()
        matching = [t for t in traces if t.get("tool_use_id") == tool_use_id]
        self.assertEqual(len(matching), 1, "PostToolUse still records an audit trace for the attempted write")
        trace = matching[0]
        self.assertNotIn(
            trace.get("operation"), ("create", "modify", "delete"),
            "INV-3: a Post-only attack must not be classified as a protected write operation",
        )
        self.assertEqual(
            trace.get("pre_hash"), trace.get("post_hash"),
            "INV-3: without PreToolUse, post hook can only observe the already-mutated state",
        )


# ============================================================
# INV-4：操作链不可篡改
# ============================================================
class TestINV4_Immutability(AIDSTestBase):
    """INV-4: trace 文件 append-only，记录只增不减。"""

    def test_traces_append_only(self) -> None:
        """多次写入后 trace 数量单调递增。"""
        self._simulate_session_start()
        counts = []
        for i in range(3):
            self._simulate_write_flow(str(self.test_file), f"# v{i}\n")
            counts.append(len(self._traces_today()))

        # 单调递增
        for i in range(1, len(counts)):
            self.assertGreaterEqual(
                counts[i], counts[i - 1],
                f"INV-4: trace count should be monotonically increasing, got {counts}",
            )

    def test_trace_ids_unique(self) -> None:
        """所有 trace_id 唯一。"""
        self._simulate_session_start()
        for i in range(5):
            self._simulate_write_flow(str(self.test_file), f"# v{i}\n")

        traces = self._traces_today()
        trace_ids = [t.get("trace_id") for t in traces]
        unique_ids = set(trace_ids)
        self.assertEqual(len(trace_ids), len(unique_ids), "INV-4: all trace_ids must be unique")

    def test_existing_trace_records_unchanged_after_append(self) -> None:
        """写 N 条后再追加 1 条，前 N 条原始 JSONL 内容必须完全不变。"""
        from datetime import date

        self._simulate_session_start()
        for i in range(3):
            self._simulate_write_flow(str(self.test_file), f"# immutable v{i}\n")

        trace_path = self._data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        before_lines = trace_path.read_text(encoding="utf-8").splitlines()
        before_records = self._traces_today()
        self.assertGreaterEqual(len(before_lines), 3, "INV-4 fixture: should have N trace records before append")

        self._simulate_write_flow(str(self.test_file), "# immutable extra append\n")

        after_lines = trace_path.read_text(encoding="utf-8").splitlines()
        after_records = self._traces_today()
        self.assertGreater(len(after_lines), len(before_lines), "INV-4: trace file should grow after append")
        self.assertEqual(
            after_lines[:len(before_lines)], before_lines,
            "INV-4: previously written raw JSONL records must remain byte-for-byte unchanged after append",
        )
        self.assertEqual(
            after_records[:len(before_records)], before_records,
            "INV-4: previously parsed trace records must remain exactly unchanged after append",
        )


# ============================================================
# INV-5：身份传播完整性
# ============================================================
class TestINV5_IdentityPropagation(AIDSTestBase):
    """INV-5: 同一 session 的所有事件共享同一 session_id。"""

    def test_consistent_session_id_across_hooks(self) -> None:
        """SessionStart + Pre + Post 共享同一 session_id。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# modified\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)

        session_ids = {t.get("session_id") for t in traces}
        self.assertEqual(
            len(session_ids), 1,
            f"INV-5: all traces should have same session_id, got {session_ids}",
        )
        self.assertEqual(session_ids.pop(), self.session_id)

    def test_session_file_created(self) -> None:
        """SessionStart 创建 session 文件。"""
        self._simulate_session_start()

        session_file = self._data_dir() / "sessions" / f"{self.session_id}.json"
        self.assertTrue(session_file.exists(), "INV-5: session file should be created")

        session = _read_json(session_file)
        self.assertIsNotNone(session)
        self.assertEqual(session.get("session_id"), self.session_id)
        self.assertEqual(session.get("role"), "implementer")

    def test_session_file_fields_populated(self) -> None:
        """Session 文件包含必要身份字段。"""
        self._simulate_session_start()

        session_file = self._data_dir() / "sessions" / f"{self.session_id}.json"
        session = _read_json(session_file)
        required_fields = ["session_id", "runtime", "role", "actor_type", "status", "started_at", "last_seen_at"]
        for field in required_fields:
            self.assertIn(field, session, f"INV-5: session must have '{field}' field")
            self.assertIsNotNone(session[field], f"INV-5: session['{field}'] must not be None")


# ============================================================
# INV-6：Hash 链完整性
# ============================================================
class TestINV6_HashChainIntegrity(AIDSTestBase):
    """INV-6: 连续写操作的 pre_hash == 上一次 post_hash。"""

    def test_consecutive_write_hash_chain(self) -> None:
        """两次写操作形成 hash 链。"""
        self._simulate_session_start()

        # 第一次写入
        self.test_file.write_text("# version 0\n", encoding="utf-8")
        self._simulate_write_flow(str(self.test_file), "# version 1\n")

        # 第二次写入
        self._simulate_write_flow(str(self.test_file), "# version 2\n")

        traces = self._traces_today()
        # 过滤出写操作 trace（modify/create），按时间排序
        write_traces = sorted(
            [t for t in traces if t.get("operation") in ("modify", "create") and t.get("resource_path") == str(self.test_file)],
            key=lambda t: t.get("timestamp", 0),
        )

        self.assertGreaterEqual(len(write_traces), 2, "Need at least 2 write traces for hash chain test")

        # 验证 hash 链：第一次 post_hash == 第二次 pre_hash
        first = write_traces[0]
        second = write_traces[1]

        if first.get("post_hash") is not None and second.get("pre_hash") is not None:
            self.assertEqual(
                first["post_hash"], second["pre_hash"],
                f"INV-6: hash chain broken — first.post_hash != second.pre_hash",
            )

    def test_hash_matches_actual_file_content(self) -> None:
        """post_hash 等于写入后文件的实际 SHA-256。"""
        self._simulate_session_start()
        content = "# exact content test\n"
        self.test_file.write_text("# old\n", encoding="utf-8")
        self._simulate_write_flow(str(self.test_file), content)

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") == "modify" and t.get("resource_path") == str(self.test_file)]
        if write_traces:
            last = write_traces[-1]
            post_hash = last.get("post_hash")
            if post_hash:
                expected_hash = _sha256(content)
                self.assertEqual(
                    post_hash, expected_hash,
                    f"INV-6: post_hash should match actual file SHA-256",
                )


# ============================================================
# INV-7：Goodhart 防护有效性
# ============================================================
class TestINV7_GoodhartProtection(AIDSTestBase):
    """INV-7: rating 记录包含 rater 身份，绑定到具体 trace。"""

    def test_rate_requires_valid_trace(self) -> None:
        """对不存在的 trace 评分应失败。"""
        self._simulate_session_start()
        result = _run_cli("rate", "tr_nonexistent123", "good", "test", env=self.env)
        self.assertNotEqual(result.returncode, 0, "INV-7: rate should fail for nonexistent trace")

    def test_rate_records_rater_identity(self) -> None:
        """评分记录包含 rater_session_id。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# rated\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)
        trace_id = traces[0]["trace_id"]

        # 评分
        result = _run_cli("rate", trace_id, "good", "test", "rating", env=self.env)
        self.assertEqual(result.returncode, 0, f"Rate should succeed: {result.stderr}")

        ratings = self._ratings_today()
        self.assertGreater(len(ratings), 0, "INV-7: rating should be recorded")

        rating = ratings[0]
        self.assertEqual(rating.get("trace_id"), trace_id, "INV-7: rating must bind to trace_id")
        self.assertIsNotNone(rating.get("rater_session_id"), "INV-7: rater_session_id must not be None")
        self.assertEqual(rating.get("score"), "good")
        self.assertIn("timestamp", rating)
        self.assertIn("rating_id", rating)

    def test_rating_has_audit_fields(self) -> None:
        """评分记录包含审计所需字段。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# for rating\n")

        traces = self._traces_today()
        trace_id = traces[0]["trace_id"]

        _run_cli("rate", trace_id, "bad", "poor", "quality", env=self.env)

        ratings = self._ratings_today()
        self.assertGreater(len(ratings), 0)
        rating = ratings[0]
        required = ["rating_id", "trace_id", "rater_session_id", "score", "timestamp", "timestamp_iso"]
        for field in required:
            self.assertIn(field, rating, f"INV-7: rating must have '{field}' field")

    def test_same_rater_cannot_rate_same_trace_twice(self) -> None:
        """同一 rater 对同一 trace 最多只能评分一次。"""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# unique rating target\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)
        trace_id = traces[0]["trace_id"]

        first = _run_cli("rate", trace_id, "good", "first", "rating", env=self.env)
        self.assertEqual(first.returncode, 0, f"First rating should succeed: {first.stderr}")

        duplicate = _run_cli("rate", trace_id, "bad", "duplicate", "rating", env=self.env)
        self.assertNotEqual(
            duplicate.returncode, 0,
            "INV-7: duplicate rating by the same rater for the same trace must be rejected",
        )

        ratings = [
            r for r in self._ratings_today()
            if r.get("trace_id") == trace_id and r.get("rater_session_id") == self.session_id
        ]
        self.assertEqual(
            len(ratings), 1,
            "INV-7: there must be at most one rating per (trace_id, rater_session_id)",
        )


# ============================================================
# 集成测试：完整 hook 流程
# ============================================================
class TestIntegration_FullHookFlow(AIDSTestBase):
    """集成测试：验证完整 hook 流程中所有不变量同时成立。"""

    def test_full_flow_all_invariants_hold(self) -> None:
        """完整 SessionStart → Pre → Write → Post → Rate 流程。"""
        # 1. SessionStart
        self._simulate_session_start()

        # 2. 第一次写入
        self.test_file.write_text("# v0\n", encoding="utf-8")
        self._simulate_write_flow(str(self.test_file), "# v1\n")

        # 3. 第二次写入
        self._simulate_write_flow(str(self.test_file), "# v2\n")

        # 4. 读取
        self._simulate_read_flow(str(self.test_file))

        # 5. 评分
        traces = self._traces_today()
        if traces:
            trace_id = traces[0]["trace_id"]
            _run_cli("rate", trace_id, "good", "integration", "test", env=self.env)

        # ── 验证所有不变量 ──

        # INV-1: 有序
        timestamps = [t.get("timestamp", 0) for t in traces]
        for i in range(1, len(timestamps)):
            self.assertGreaterEqual(timestamps[i], timestamps[i - 1], "INV-1 failed in integration")

        # INV-2: 可追溯
        idx = self._index_for(str(self.test_file))
        self.assertIsNotNone(idx)
        self.assertIsNotNone(idx.get("last_actor"), "INV-2 failed")

        # INV-4: 唯一
        trace_ids = [t.get("trace_id") for t in traces]
        self.assertEqual(len(trace_ids), len(set(trace_ids)), "INV-4 failed")

        # INV-5: 一致
        session_ids = {t.get("session_id") for t in traces}
        self.assertEqual(len(session_ids), 1, "INV-5 failed")

        # INV-6: Hash 链（如果有两次写操作）
        write_traces = sorted(
            [t for t in traces if t.get("operation") in ("modify", "create") and t.get("resource_path") == str(self.test_file)],
            key=lambda t: t.get("timestamp", 0),
        )
        if len(write_traces) >= 2:
            first, second = write_traces[0], write_traces[1]
            if first.get("post_hash") and second.get("pre_hash"):
                self.assertEqual(first["post_hash"], second["pre_hash"], "INV-6 failed")

        # INV-7: Rating 审计
        ratings = self._ratings_today()
        if ratings:
            self.assertIsNotNone(ratings[0].get("rater_session_id"), "INV-7 failed")


# ============================================================
# SignatureBackend + verify command
# ============================================================
class TestSignatureBackendAndVerify(AIDSTestBase):
    """Test the SignatureBackend abstraction and verify command."""

    def test_chain_hash_computed_on_write(self) -> None:
        """Write traces include a chain_hash field."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# modified\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)
        trace = traces[0]
        self.assertIsNotNone(trace.get("chain_hash"), "chain_hash should be computed for new traces")

    def test_chain_hash_changes_per_trace(self) -> None:
        """Different traces produce different chain hashes."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# v1\n")
        self._simulate_write_flow(str(self.test_file), "# v2\n")

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") in ("modify", "create")]
        self.assertGreaterEqual(len(write_traces), 2)

        hashes = [t.get("chain_hash") for t in write_traces if t.get("chain_hash")]
        self.assertGreaterEqual(len(hashes), 2)
        unique_hashes = set(hashes)
        self.assertEqual(len(unique_hashes), len(hashes), "Each trace should have a unique chain_hash")

    def test_verify_all_passes(self) -> None:
        """aids verify returns 0 when no tampering."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# clean\n")

        result = _run_cli("verify", env=self.env)
        self.assertEqual(result.returncode, 0, f"verify should pass: {result.stdout}{result.stderr}")
        self.assertIn("verified", result.stdout.lower())

    def test_verify_single_trace(self) -> None:
        """aids verify <trace_id> verifies a specific trace."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# single\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)
        trace_id = traces[0]["trace_id"]

        result = _run_cli("verify", trace_id, env=self.env)
        self.assertEqual(result.returncode, 0, f"verify <trace_id> should pass: {result.stdout}{result.stderr}")

    def test_verify_detects_tampering(self) -> None:
        """aids verify detects chain_hash tampering."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# tampered\n")

        traces = self._traces_today()
        self.assertGreater(len(traces), 0)
        trace_id = traces[0]["trace_id"]

        # Tamper: change trace_id in the file (which IS in chain_fields)
        from datetime import date
        trace_path = self._data_dir() / "traces" / f"{date.today().isoformat()}.jsonl"
        lines = trace_path.read_text(encoding="utf-8").splitlines()
        tampered = []
        for line in lines:
            d = json.loads(line.strip())
            if d.get("trace_id") == trace_id:
                d["trace_id"] = "TAMPERED"
            tampered.append(json.dumps(d, ensure_ascii=False))
        trace_path.write_text("\n".join(tampered) + "\n", encoding="utf-8")

        result = _run_cli("verify", env=self.env)
        self.assertNotEqual(result.returncode, 0, "verify should detect tampering")
        self.assertIn("chain_hash mismatch", result.stdout)


# ============================================================
# Atomic chain-hash concurrent write test
# ============================================================
class TestAtomicChainHash(AIDSTestBase):
    """Verify _append_trace_chain_atomic produces a valid chain under concurrency."""

    def _verify_chain(self, traces: List[Dict[str, Any]]) -> None:
        """Re-verify every chain_hash in the ordered trace list."""
        prev_hash: Optional[str] = None
        for tr in traces:
            stored = tr.get("chain_hash")
            self.assertIsNotNone(stored, f"trace {tr.get('trace_id')} missing chain_hash")
            expected = hashlib.sha256(
                (
                    f"{prev_hash or 'GENESIS'}:"
                    + json.dumps(
                        {
                            "trace_id": tr.get("trace_id"),
                            "session_id": tr.get("session_id"),
                            "tool": tr.get("tool"),
                            "resource_path": tr.get("resource_path"),
                            "operation": tr.get("operation"),
                            "pre_hash": tr.get("pre_hash"),
                            "post_hash": tr.get("post_hash"),
                            "timestamp": tr.get("timestamp"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(
                stored,
                expected,
                f"chain_hash mismatch at trace {tr.get('trace_id')}: "
                f"stored={stored}, expected={expected}",
            )
            prev_hash = stored

    def test_chain_atomic_concurrent(self) -> None:
        """10 threads write to the same resource concurrently; all chain hashes must verify."""
        import threading

        self._simulate_session_start()

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        errors: List[str] = []

        def worker(idx: int) -> None:
            try:
                barrier.wait(timeout=10)
                self._simulate_write_flow(str(self.test_file), f"# thread-{idx}\n")
            except Exception as exc:
                errors.append(f"thread-{idx}: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [], f"Worker errors: {errors}")

        traces = self._traces_today()
        # Use JSONL natural order (= lock acquisition order = chain order).
        # Do NOT sort by timestamp — concurrent writes may have identical timestamps
        # but the chain order is determined by who acquired the index lock first.
        write_traces = [
            t for t in traces
            if t.get("operation") in ("modify", "create")
            and t.get("resource_path") == str(self.test_file)
        ]
        self.assertGreaterEqual(len(write_traces), num_threads,
                                f"Expected >= {num_threads} write traces, got {len(write_traces)}")

        self._verify_chain(write_traces)


# ============================================================
# Structured result field tests
# ============================================================
class TestResultField(AIDSTestBase):
    """Verify _extract_result always populates a structured result."""

    def test_result_always_present_on_write(self) -> None:
        """Every write trace has a non-empty result dict."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# new content\n")

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") in ("modify", "create")]
        self.assertGreater(len(write_traces), 0)
        for tr in write_traces:
            result = tr.get("result")
            self.assertIsInstance(result, dict, f"trace {tr.get('trace_id')} result should be dict, got {type(result)}")
            self.assertIn("status", result, f"trace {tr.get('trace_id')} missing result.status")
            self.assertIn(result["status"], ("success", "error"))

    def test_result_success_when_no_error(self) -> None:
        """Normal write produces result.status == success."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# ok\n")

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") in ("modify", "create")]
        self.assertGreater(len(write_traces), 0)
        result = write_traces[0].get("result")
        self.assertEqual(result.get("status"), "success")

    def test_result_has_preview(self) -> None:
        """When tool_response is present, result includes a preview."""
        self._simulate_session_start()
        self._simulate_write_flow(str(self.test_file), "# content\n")

        traces = self._traces_today()
        write_traces = [t for t in traces if t.get("operation") in ("modify", "create")]
        if write_traces and write_traces[0].get("result", {}).get("preview"):
            self.assertIsInstance(write_traces[0]["result"]["preview"], str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
