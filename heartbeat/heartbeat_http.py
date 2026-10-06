"""
heartbeat_http.py —— Hub 端心跳接收 HTTP 服务

将 heartbeat_receiver.receive_heartbeat_data() 暴露为 HTTP:
  POST /heartbeat  -> 接收 Agent 心跳，返回 {"status":"ok"}
  GET  /heartbeat  -> 查询各 Agent 在线状态

默认端口 5000，与 heartbeat/AKO_heartbeat_client.py 的
DEFAULT_HUB_URL = http://localhost:5000/heartbeat 对齐。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# 确保可导入同包模块
_HUB_ROOT = Path(__file__).resolve().parent.parent
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

from heartbeat.heartbeat_receiver import (
    get_agents_status,
    receive_heartbeat_data,
    receive_llm_call_data,
)

PORT = 5000

# 默认数据库路径(与 hub 元数据库一致)
_DEFAULT_DB = str(_HUB_ROOT / "ako_hub.db")


def _ensure_schema(db_path: str) -> None:
    """确保心跳相关表存在(heartbeat_receiver 写入所需的 schema)。"""
    schema = """
    CREATE TABLE IF NOT EXISTS agents_registry (
        agent_id TEXT PRIMARY KEY,
        display_name TEXT,
        agent_type TEXT,
        heartbeat_interval INTEGER DEFAULT 30
    );
    CREATE TABLE IF NOT EXISTS heartbeats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        timestamp TEXT,
        status TEXT,
        cpu_percent REAL,
        memory_mb REAL,
        disk_percent REAL,
        last_task TEXT,
        last_task_status TEXT,
        response_time_ms REAL,
        task_total INTEGER DEFAULT 0,
        task_success INTEGER DEFAULT 0,
        task_failed INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        level TEXT,
        message TEXT,
        context TEXT,
        timestamp TEXT
    );
    CREATE TABLE IF NOT EXISTS llm_ingest_stats (
        agent_id TEXT,
        hour TEXT,
        received_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        last_error TEXT,
        PRIMARY KEY (agent_id, hour)
    );
    CREATE TABLE IF NOT EXISTS llm_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        entry_point TEXT,
        provider TEXT,
        model TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        tokens_missing INTEGER DEFAULT 0,
        duration_ms REAL,
        success INTEGER DEFAULT 0,
        error_type TEXT,
        error_msg TEXT,
        recorded_at TEXT
    );
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


class HeartbeatHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/llm_call":
            data = self._read_json_body()
            result = receive_llm_call_data(data, db_path=_DEFAULT_DB)
            code = 200 if result.get("status") == "ok" else 400
            self._send_json(code, result)
            return

        if path != "/heartbeat":
            self._send_json(404, {"error": "not found"})
            return
        data = self._read_json_body()
        result = receive_heartbeat_data(data, db_path=_DEFAULT_DB)
        code = 200 if result.get("status") == "ok" else 400
        self._send_json(code, result)

    def do_GET(self):
        if self.path.split("?")[0] != "/heartbeat":
            self._send_json(404, {"error": "not found"})
            return
        result = get_agents_status(db_path=_DEFAULT_DB)
        self._send_json(200, result)

    def log_message(self, format, *args):
        print(f"[heartbeat_http] {self.log_date_time_string()} {format % args}")


def run(port: int = PORT):
    _ensure_schema(_DEFAULT_DB)
    server = HTTPServer(("0.0.0.0", port), HeartbeatHandler)
    print(f"AKO_hub 心跳接收服务已启动: http://0.0.0.0:{port}/heartbeat")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n心跳服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()