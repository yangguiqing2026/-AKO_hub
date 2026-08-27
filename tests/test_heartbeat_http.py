"""
test_heartbeat_http.py —— 心跳接收往返验证(纯函数，不启动 HTTP 服务)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from heartbeat.heartbeat_http import _ensure_schema
from heartbeat.heartbeat_receiver import get_agents_status, receive_heartbeat_data


class TestHeartbeatRoundTrip(unittest.TestCase):
    def test_receive_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_hb.db")
            _ensure_schema(db_path)

            # 模拟 law_agent SyncBridge._build_payload 的字段
            payload = {
                "agent_id": "law_agent",
                "timestamp": "2026-08-22T02:00:00+00:00",
                "status": "alive",
                "cpu_percent": 1.5,
                "memory_mb": 123.4,
                "disk_percent": 50,
                "task_total": 10,
                "task_success": 9,
                "task_failed": 1,
                "last_task": "legislation.draft",
                "last_task_status": "success",
                "response_time_ms": 120.0,
            }

            result = receive_heartbeat_data(payload, db_path=db_path)
            self.assertEqual(result["status"], "ok", result)

            status = get_agents_status(db_path=db_path)
            agents = status.get("agents", [])
            self.assertEqual(len(agents), 1)
            self.assertEqual(agents[0]["agent_id"], "law_agent")
            self.assertEqual(agents[0]["status"], "alive")
            self.assertEqual(agents[0]["task_success"], 9)


if __name__ == "__main__":
    unittest.main()