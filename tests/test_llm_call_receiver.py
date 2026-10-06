"""
test_llm_call_receiver.py —— LLM 调用记录接收与查询往返验证(纯函数，不启动 HTTP 服务)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from heartbeat.heartbeat_http import _ensure_schema
from heartbeat.heartbeat_receiver import (
    get_llm_calls,
    get_llm_ingest_stats,
    receive_llm_call_data,
)


class TestLLMCallRoundTrip(unittest.TestCase):
    def test_receive_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_llm.db")
            _ensure_schema(db_path)

            # 模拟 law_agent LLMEngine 成功调用 ollama 的字段
            payload = {
                "agent_id": "AKO_law_agent",
                "entry_point": "law.llm_engine._call_ollama",
                "provider": "ollama",
                "model": "qwen2.5:7b",
                "prompt_tokens": 30,
                "completion_tokens": 5,
                "total_tokens": 35,
                "duration_ms": 7800.8,
                "success": True,
            }

            result = receive_llm_call_data(payload, db_path=db_path)
            self.assertEqual(result["status"], "ok", result)

            rows = get_llm_calls(db_path=db_path)
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0]["agent_id"], "AKO_law_agent")
            self.assertEqual(rows[0]["entry_point"], "law.llm_engine._call_ollama")
            self.assertEqual(rows[0]["total_tokens"], 35)
            self.assertEqual(rows[0]["tokens_missing"], 0)
            self.assertEqual(rows[0]["success"], 1)


    def test_tokens_missing_when_provider_omits_usage(self):
        """provider 不返回 token 时须显式标记缺失，不得填 0 伪装成零消耗。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_llm.db")
            _ensure_schema(db_path)

            # 模拟 hub 链路：llama.cpp 不返回 usage（2026-09-14 实测）
            payload = {
                "agent_id": "AKO_hub",
                "entry_point": "hub.hub_api.call_llm",
                "provider": "llama_cpp",
                "model": "openai/qwen3-14b",
                "duration_ms": 120.0,
                "success": True,
            }

            result = receive_llm_call_data(payload, db_path=db_path)
            self.assertEqual(result["status"], "ok", result)

            rows = get_llm_calls(db_path=db_path)
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0]["tokens_missing"], 1)
            self.assertIsNone(rows[0]["prompt_tokens"])
            self.assertIsNone(rows[0]["completion_tokens"])
            self.assertIsNone(rows[0]["total_tokens"])


    def test_unwritable_db_path_returns_error_without_raising(self):
        """观测层自身的故障不得抛给业务方（R6：不能成为新故障点）。"""
        bad_path = os.path.join(tempfile.gettempdir(), "ako_no_such_dir_xyz", "nope.db")

        result = receive_llm_call_data(
            {"agent_id": "AKO_law_agent", "entry_point": "law.llm_engine._call_ollama"},
            db_path=bad_path,
        )

        self.assertEqual(result["status"], "error", result)
        self.assertIn("message", result)


class TestLLMCallEndpoint(unittest.TestCase):
    """真实起服务验证 POST /llm_call 路由（端点级，非纯函数）。"""

    def test_post_llm_call_records_and_returns_200(self):
        import json
        import threading
        import urllib.request
        from http.server import HTTPServer

        import heartbeat.heartbeat_http as hh

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_ep.db")
            hh._ensure_schema(db_path)
            original_db = hh._DEFAULT_DB
            hh._DEFAULT_DB = db_path

            server = HTTPServer(("127.0.0.1", 0), hh.HeartbeatHandler)
            port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                payload = {
                    "agent_id": "AKO_web_consult_agent",
                    "entry_point": "web_consult.llm_router.chat_stream",
                    "provider": "minimax",
                    "model": "abab6.5",
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "duration_ms": 950.0,
                    "success": True,
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/llm_call",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(body["status"], "ok", body)

                rows = get_llm_calls(db_path=db_path)
                self.assertEqual(len(rows), 1, rows)
                self.assertEqual(rows[0]["agent_id"], "AKO_web_consult_agent")
                self.assertEqual(rows[0]["entry_point"], "web_consult.llm_router.chat_stream")
                self.assertEqual(rows[0]["total_tokens"], 120)
                self.assertEqual(rows[0]["tokens_missing"], 0)
            finally:
                server.shutdown()
                server.server_close()
                hh._DEFAULT_DB = original_db


class TestIngestStats(unittest.TestCase):
    """P0：观测层自身的失败必须可见——不得出现"静默的数据空洞"。"""

    def test_accepted_record_increments_received_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_stats.db")
            _ensure_schema(db_path)

            receive_llm_call_data(
                {"agent_id": "AKO_law_agent", "entry_point": "law.llm_engine._call_ollama",
                 "success": True},
                db_path=db_path,
            )
            receive_llm_call_data(
                {"agent_id": "AKO_law_agent", "entry_point": "law.llm_engine._call_ollama",
                 "success": True},
                db_path=db_path,
            )

            stats = get_llm_ingest_stats(db_path=db_path)
            self.assertEqual(len(stats), 1, stats)
            self.assertEqual(stats[0]["agent_id"], "AKO_law_agent")
            self.assertEqual(stats[0]["received_count"], 2)
            self.assertEqual(stats[0]["rejected_count"], 0)

    def test_rejected_record_is_counted_with_reason(self):
        """缺必需字段的记录被拒时，必须留下计数与原因——否则数据空洞无人知晓。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_stats.db")
            _ensure_schema(db_path)

            result = receive_llm_call_data({"agent_id": "AKO_hub"}, db_path=db_path)

            self.assertEqual(result["status"], "error", result)
            self.assertIn("entry_point", result["message"])

            stats = get_llm_ingest_stats(db_path=db_path)
            self.assertEqual(len(stats), 1, stats)
            self.assertEqual(stats[0]["agent_id"], "AKO_hub")
            self.assertEqual(stats[0]["received_count"], 0)
            self.assertEqual(stats[0]["rejected_count"], 1)
            self.assertIn("entry_point", stats[0]["last_error"])


class TestBulkWrite(unittest.TestCase):
    """特征化测试（非 TDD）：锁定高负载下不丢记录，并为 P1-1 提供容量数据。

    P1-1：llm_calls 与心跳共用 ako_hub.db，需先测写入量再决定是否拆库。
    """

    def test_bulk_insert_1000_all_recorded(self):
        import time

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_bulk.db")
            _ensure_schema(db_path)

            started = time.perf_counter()
            for i in range(1000):
                result = receive_llm_call_data(
                    {
                        "agent_id": "AKO_hub",
                        "entry_point": "hub.hub_api.call_llm",
                        "provider": "llama_cpp",
                        "model": f"model-{i % 5}",
                        "total_tokens": i,
                        "success": True,
                    },
                    db_path=db_path,
                )
                self.assertEqual(result["status"], "ok", f"第 {i} 条写入失败: {result}")
            elapsed = time.perf_counter() - started

            rows = get_llm_calls(db_path=db_path, limit=2000)
            self.assertEqual(len(rows), 1000)

            stats = get_llm_ingest_stats(db_path=db_path)
            self.assertEqual(sum(s["received_count"] for s in stats), 1000)

            # 容量基线：>1000 条/秒 说明共库写入不构成瓶颈
            print(f"\n[P1-1 容量基线] 1000 条写入耗时 {elapsed:.2f}s "
                  f"→ {1000 / elapsed:.0f} 条/秒")


if __name__ == "__main__":
    unittest.main()
