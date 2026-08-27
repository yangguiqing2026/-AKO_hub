"""
heartbeat_server.py — Hub 端心跳接收 HTTP 服务。

职责：
1. 在 5000 端口暴露 POST /heartbeat 端点，接收各 Agent 心跳。
2. 复用 heartbeat_receiver.receive_heartbeat_data 写入 SQLite。
3. 提供 GET /health 与 GET /agents 查询接口。

仅使用 Python 标准库，不引入 FastAPI/uvicorn，与 hub_http_server.py 风格一致。

文档编号: AGE-TECH-AKO-HUB-020 §HeartbeatReceiver
"""

from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

# ── 常量 ───────────────────────────────────────────────────────────
PORT: int = 5000
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "ako_hub.db"
SCHEMA_FILE = PROJECT_ROOT / "database" / "schema_heartbeat.sql"

# 兼容两种运行方式（包导入 / 直接脚本执行）
try:
    from heartbeat.heartbeat_receiver import (
        receive_heartbeat_data,
        get_agents_status,
        seed_agents_registry,
    )
except ImportError:  # 直接以脚本运行于 heartbeat/ 目录时
    from heartbeat_receiver import (  # type: ignore
        receive_heartbeat_data,
        get_agents_status,
        seed_agents_registry,
    )


def init_heartbeat_db(db_path: Optional[str] = None) -> None:
    """初始化心跳数据库表结构（幂等）。"""
    target = Path(db_path) if db_path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    if SCHEMA_FILE.exists():
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
    else:
        # 兜底：仅建最小三表，确保服务可启动
        schema = """
        CREATE TABLE IF NOT EXISTS agents_registry (
            agent_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
            agent_type TEXT NOT NULL DEFAULT 'unknown',
            alert_level TEXT NOT NULL DEFAULT 'warning',
            heartbeat_interval INTEGER NOT NULL DEFAULT 30
        );
        CREATE TABLE IF NOT EXISTS heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL,
            timestamp TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'alive',
            cpu_percent REAL, memory_mb REAL, disk_percent REAL,
            task_total INTEGER DEFAULT 0, task_success INTEGER DEFAULT 0,
            task_failed INTEGER DEFAULT 0, last_task TEXT,
            last_task_status TEXT, response_time_ms REAL
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT,
            agent_id TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'INFO',
            message TEXT NOT NULL DEFAULT '', context TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """

    conn = sqlite3.connect(str(target))
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()

    # 幂等登记默认 Agent 清单，使 D:/AKO 下尚未上报心跳的 Agent 也出现在看板中（离线可见）
    seed_agents_registry(str(target))


class HeartbeatHandler(BaseHTTPRequestHandler):
    """处理心跳接收相关 HTTP 请求。"""

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "heartbeat"})
            return

        if path == "/agents":
            self._send_json(200, get_agents_status(str(DB_PATH)))
            return

        self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]

        if path == "/heartbeat":
            data = self._read_json_body()
            result = receive_heartbeat_data(data, str(DB_PATH))
            code = 200 if result.get("status") == "ok" else 400
            self._send_json(code, result)
            return

        self._send_json(404, {"error": "not found", "path": path})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def run(port: int = PORT, db_path: Optional[str] = None) -> None:
    """启动心跳接收服务。"""
    init_heartbeat_db(db_path)
    server = HTTPServer(("0.0.0.0", port), HeartbeatHandler)
    print(f"AKO_hub 心跳接收服务已启动: http://0.0.0.0:{port}")
    print("端点: POST /heartbeat | GET /health | GET /agents")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n心跳服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()