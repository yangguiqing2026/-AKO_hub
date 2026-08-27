# ============================================
# Author: AKO_studio
# Agent: AKO_hub
# Module: hub_http_server - Hub HTTP 层（方案B）
# Description: 为 Hub 提供轻量 HTTP 接口，供 AKO_audit_agent
#   等 Spoke Agent 通过 HTTP 完成注册与事件订阅。
#   仅使用 Python 标准库，不引入 FastAPI/uvicorn。
#
# 端点:
#   GET  /health        -> {"status":"ok"}
#   POST /register      -> 接收 agent_card JSON，登记并产出注册事件
#   GET  /events/poll   -> 拉取并清空待处理事件队列
#   POST /events        -> 手动投递事件（供 Hub 内部/其他系统触发）
# ============================================

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

PORT = 8080
REGISTRY_FILE = Path(__file__).resolve().parent / "registry" / "http_registered_agents.json"

_registry_lock = threading.Lock()
_events_lock = threading.Lock()
_events = []


def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_registry(registry: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def enqueue_event(event_type: str, agent_id: str, data: Optional[dict] = None) -> None:
    """向事件队列加入一条事件"""
    with _events_lock:
        _events.append(
            {
                "type": event_type,
                "agent_id": agent_id,
                "target_agent": agent_id,
                "data": data or {},
                "timestamp": datetime.now().isoformat(),
            }
        )


class HubHTTPHandler(BaseHTTPRequestHandler):
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

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/events/poll":
            with _events_lock:
                events = list(_events)
                _events.clear()
            self._send_json(200, {"events": events})
            return

        self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/register":
            card = self._read_json_body()
            agent_id = card.get("agent_id") or card.get("name") or card.get("id")
            if not agent_id:
                self._send_json(400, {"status": "FAIL", "reason": "缺少 agent_id"})
                return

            # 身份约束：author 必须为 AKO_studio（与 audit_agent 注册协议一致）
            author = card.get("author")
            if author and author != "AKO_studio":
                self._send_json(
                    400, {"status": "FAIL", "reason": f"author={author} != AKO_studio"}
                )
                return

            with _registry_lock:
                registry = _load_registry()
                registered_before = agent_id in registry
                registry[agent_id] = {
                    "agent_id": agent_id,
                    "card": card,
                    "registered_at": datetime.now().isoformat(),
                    "status": "active",
                }
                _save_registry(registry)

            enqueue_event("register", agent_id, {"card": card})
            self._send_json(
                200,
                {
                    "status": "SUCCESS",
                    "agent_id": agent_id,
                    "registered": not registered_before,
                },
            )
            return

        if path == "/events":
            payload = self._read_json_body()
            event_type = payload.get("type", "unknown")
            agent_id = payload.get("agent_id") or payload.get("target_agent", "")
            if not agent_id:
                self._send_json(400, {"error": "缺少 agent_id 或 target_agent"})
                return
            enqueue_event(event_type, agent_id, payload.get("data"))
            self._send_json(200, {"status": "ENQUEUED"})
            return

        self._send_json(404, {"error": "not found", "path": path})

    def log_message(self, format, *args):
        # 保持日志简洁，仅打印请求行
        print(f"[{self.log_date_time_string()}] {format % args}")


def run(port: int = PORT):
    server = HTTPServer(("0.0.0.0", port), HubHTTPHandler)
    print(f"AKO_hub HTTP 服务已启动: http://0.0.0.0:{port}")
    print("端点: GET /health | POST /register | GET /events/poll | POST /events")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()