"""
heartbeat_receiver.py — Hub 端心跳接收服务。

核心职责：
1. 接收各 Agent 的心跳数据
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




def _get_db(db_path: str = "ako_hub.db") -> sqlite3.Connection:
    """获取 SQLite 连接。"""
    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── 常量 ───────────────────────────────────────────────────────────
DB_TIMEOUT: float = 5.0        # SQLite 写入超时（秒）


# ═════════════════════════════════════════════════════════════════════
# 心跳接收核心逻辑（纯函数，无 Web 依赖）
# ═════════════════════════════════════════════════════════════════════


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


def receive_heartbeat_data(data: Dict[str, Any], db_path: str = "ako_hub.db") -> Dict[str, Any]:
    """
    接收并处理 Agent 心跳数据（纯函数，无 Web 依赖）。

    Args:
        data: 心跳数据 { agent_id, timestamp, status, cpu_percent, ... }
        db_path: SQLite 数据库路径

    Returns:
        {"status": "ok"} 或 {"status": "error", "message": str}
    """
    try:
        agent_id: Optional[str] = data.get("agent_id")
        if not agent_id:
            return {"status": "error", "message": "缺少 agent_id"}

        conn = _get_db(db_path)
        try:
            _upsert_agent_registry(conn, agent_id, data)
            _insert_heartbeat(conn, agent_id, data)
            conn.commit()
        finally:
            conn.close()

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def get_agents_status(db_path: str = "ako_hub.db", offline_only: bool = False) -> Dict[str, Any]:
    """
    查询所有 Agent 的当前状态。

    Args:
        db_path: SQLite 数据库路径
        offline_only: 是否只返回离线 Agent

    Returns:
        {"agents": [...]}
    """
    try:
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

        return {"agents": agents}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}
