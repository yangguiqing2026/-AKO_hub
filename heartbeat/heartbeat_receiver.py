"""
heartbeat_receiver.py — Hub 端心跳接收服务。

Flask Blueprint，负责：
1. 接收各 Agent 的心跳 POST
2. 写入 SQLite（heartbeats 表 + 日志）
3. 维护 agents_registry 在线状态

文档编号: AGE-TECH-AKO-HUB-020 §HeartbeatReceiver
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, Response, current_app, jsonify, request


# ── 常量 ───────────────────────────────────────────────────────────
BP_NAME: str = "heartbeat"
DB_TIMEOUT: float = 5.0        # SQLite 写入超时（秒）


def _get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """获取 SQLite 连接（优先从 Flask app config 读取路径）。"""
    if db_path is None:
        try:
            db_path = current_app.config.get("HEARTBEAT_DB_PATH", "ako_hub.db")
        except RuntimeError:
            db_path = "ako_hub.db"

    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ═════════════════════════════════════════════════════════════════════
# Flask Blueprint
# ═════════════════════════════════════════════════════════════════════

heartbeat_bp = Blueprint(BP_NAME, __name__)


@heartbeat_bp.route("/heartbeat", methods=["POST"])
def receive_heartbeat() -> tuple[Response, int]:
    """
    接收 Agent 心跳。

    POST /heartbeat
    Body: { agent_id, session_id, timestamp, status, cpu_percent,
            memory_mb, disk_percent, task_total, task_success,
            task_failed, last_task, last_task_status, response_time_ms,
            recent_tasks, ... }

    Returns:
        {"status": "ok"} 或 {"status": "error", "message": str}
    """
    try:
        data: Dict[str, Any] = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "empty body"}), 400

        agent_id: Optional[str] = data.get("agent_id")
        if not agent_id:
            return jsonify({"status": "error", "message": "缺少 agent_id"}), 400

        db_path = current_app.config.get("HEARTBEAT_DB_PATH", "ako_hub.db")
        conn = _get_db(db_path)

        try:
            _upsert_agent_registry(conn, agent_id, data)
            _insert_heartbeat(conn, agent_id, data)
            conn.commit()
        finally:
            conn.close()

        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


@heartbeat_bp.route("/heartbeat/status", methods=["GET"])
def get_agents_status() -> tuple[Response, int]:
    """
    查询所有 Agent 的当前状态（用于 Dashboard）。

    GET /heartbeat/status?offline_only=0

    Returns:
        {"agents": [...]}
    """
    try:
        offline_only = request.args.get("offline_only", "0") == "1"
        db_path = current_app.config.get("HEARTBEAT_DB_PATH", "ako_hub.db")
        conn = _get_db(db_path)

        try:
            cur = conn.execute("""
                SELECT
                    a.agent_id, a.display_name, a.agent_type,
                    h.timestamp AS last_heartbeat,
                    h.status, h.cpu_percent, h.memory_mb,
                    h.task_total, h.task_success, h.task_failed,
                    h.last_task, h.last_task_status,
                    CAST((strftime('%s','now') - strftime('%s', h.timestamp)) AS INTEGER) AS seconds_ago
                FROM agents_registry a
                LEFT JOIN (
                    SELECT agent_id, MAX(id) AS latest_id
                    FROM heartbeats
                    GROUP BY agent_id
                ) latest ON a.agent_id = latest.agent_id
                LEFT JOIN heartbeats h ON h.id = latest.latest_id
                ORDER BY a.agent_id
            """)

            agents = []
            for row in cur.fetchall():
                d = dict(row)
                d["online"] = (d["seconds_ago"] or 999) < 90
                agents.append(d)

        finally:
            conn.close()

        if offline_only:
            agents = [a for a in agents if not a["online"]]

        return jsonify({"agents": agents})

    except Exception as e:
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


# ── 辅助函数 ───────────────────────────────────────────────────────

def _upsert_agent_registry(conn: sqlite3.Connection, agent_id: str, data: Dict[str, Any]) -> None:
    """
    自动注册/更新 Agent 信息。

    若 agents_registry 中无此 agent，自动创建一条基础记录。
    """
    cur = conn.execute(
        "SELECT agent_id FROM agents_registry WHERE agent_id = ?",
        (agent_id,),
    )
    if cur.fetchone() is None:
        conn.execute(
            """
            INSERT INTO agents_registry (agent_id, display_name, agent_type, heartbeat_interval)
            VALUES (?, ?, ?, ?)
            """,
            (
                agent_id,
                data.get("display_name", agent_id),
                data.get("agent_type", "unknown"),
                30,
            ),
        )


def _insert_heartbeat(conn: sqlite3.Connection, agent_id: str, data: Dict[str, Any]) -> None:
    """写入一条心跳记录。"""
    conn.execute(
        """
        INSERT INTO heartbeats
            (agent_id, timestamp, status, cpu_percent, memory_mb, disk_percent,
             last_task, last_task_status, response_time_ms, task_total, task_success, task_failed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            data.get("status", "unknown"),
            data.get("cpu_percent"),
            data.get("memory_mb"),
            data.get("disk_percent"),
            data.get("last_task"),
            data.get("last_task_status"),
            data.get("response_time_ms"),
            data.get("task_total", 0),
            data.get("task_success", 0),
            data.get("task_failed", 0),
        ),
    )

    # ── 日志写入（如有 recent_tasks） ──
    recent_tasks = data.get("recent_tasks", [])
    for task in recent_tasks:
        log_level = "INFO" if task.get("status") == "completed" else "WARN"
        conn.execute(
            """
            INSERT INTO logs (agent_id, level, message, context, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                log_level,
                f"task {task.get('task_id')} → {task.get('status')}",
                json.dumps(task, ensure_ascii=False),
                task.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )


def create_heartbeat_blueprint() -> Blueprint:
    """创建心跳 Blueprint（工厂函数，供外部 app 注册）。"""
    return heartbeat_bp


class HeartbeatReceiver:
    """
    Hub 端心跳接收服务（封装 Blueprint 注册 + 独立启动能力）。

    用法:
        from flask import Flask
        from heartbeat import HeartbeatReceiver

        app = Flask(__name__)
        app.config["HEARTBEAT_DB_PATH"] = "ako_hub.db"
        receiver = HeartbeatReceiver()
        receiver.init_app(app)

    独立运行:
        python heartbeat_receiver.py
    """

    def __init__(self, db_path: str = "ako_hub.db") -> None:
        self.db_path = db_path

    def init_app(self, app) -> None:
        """注册 Blueprint 到 Flask 应用。"""
        app.config.setdefault("HEARTBEAT_DB_PATH", self.db_path)
        app.register_blueprint(heartbeat_bp)

    @staticmethod
    def run_standalone(host: str = "0.0.0.0", port: int = 5000, db_path: str = "ako_hub.db") -> None:
        """独立启动 Flask 接收服务（开发/调试用）。"""
        from flask import Flask

        app = Flask(__name__)
        app.config["HEARTBEAT_DB_PATH"] = db_path
        app.register_blueprint(heartbeat_bp)

        print(f"心跳接收服务启动 → http://{host}:{port}")
        app.run(host=host, port=port, debug=False)


# ── 自检 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    HeartbeatReceiver.run_standalone(port=5000)
