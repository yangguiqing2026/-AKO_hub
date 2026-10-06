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


# ── 常量 ───────────────────────────────────────────────────────────
DB_TIMEOUT: float = 5.0        # SQLite 写入超时（秒）

# ── 默认 Agent 清单（看板基础注册表） ────────────────────────────
# D:/AKO 下已存在但尚未内置心跳上报的 Agent，先登记进 agents_registry，
# 使其在「健康巡检 / 总览看板」中可见（未上报心跳时为离线状态）。
# 一旦这些 Agent 上报心跳，心跳字段会被正常更新为在线。
SEED_AGENTS: list[tuple[str, str, str]] = [
    # (agent_id, display_name, agent_type)  —— 仅 registry 模块不可用时的启动兜底
    ("AKO_client_profile_agent", "客户画像 Agent", "business"),
    ("AKO_clinic_agent", "集群健康诊疗 Agent", "ops"),
    ("AKO_kb_agent", "知识库检索 Agent", "base"),
    ("AKO_knowledge", "知识库服务", "base"),
    ("AKO_media_agent", "内容营销 Agent", "design"),
    ("AKO_file_tag_manager", "文件标签管理 Agent", "base"),
]


def _get_db(db_path: str = "ako_hub.db") -> sqlite3.Connection:
    """获取 SQLite 连接。"""
    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
    else:
        # 已有记录时，若上报带 display_name/agent_type，则补全展示信息
        conn.execute(
            """
            UPDATE agents_registry
            SET display_name = CASE WHEN display_name = '' OR display_name = agent_id
                                    THEN ? ELSE display_name END,
                agent_type = CASE WHEN agent_type = 'unknown' THEN ? ELSE agent_type END
            WHERE agent_id = ?
            """,
            (
                data.get("display_name", agent_id),
                data.get("agent_type", "unknown"),
                agent_id,
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


def _insert_llm_call(conn: sqlite3.Connection, data: Dict[str, Any]) -> None:
    """写入一条 LLM 调用记录。

    token 缺失时保持 NULL 并把 tokens_missing 置 1——不得填 0 伪装成"零消耗"。
    """
    prompt_tokens = data.get("prompt_tokens")
    completion_tokens = data.get("completion_tokens")
    total_tokens = data.get("total_tokens")
    tokens_missing = 1 if None in (prompt_tokens, completion_tokens, total_tokens) else 0

    conn.execute(
        """
        INSERT INTO llm_calls
            (agent_id, entry_point, provider, model,
             prompt_tokens, completion_tokens, total_tokens, tokens_missing,
             duration_ms, success, error_type, error_msg, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("agent_id"),
            data.get("entry_point"),
            data.get("provider"),
            data.get("model"),
            prompt_tokens,
            completion_tokens,
            total_tokens,
            tokens_missing,
            data.get("duration_ms"),
            1 if data.get("success") else 0,
            data.get("error_type"),
            data.get("error_msg"),
            data.get("recorded_at", datetime.now(timezone.utc).isoformat()),
        ),
    )


def _bump_ingest_stats(
    conn: sqlite3.Connection,
    agent_id: str,
    received: int = 0,
    rejected: int = 0,
    error: Optional[str] = None,
) -> None:
    """按 (agent_id, 小时) 累加采集计数。

    P0：观测层自身的失败必须可见——否则会出现"数据空洞而无人知晓"。
    """
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
    conn.execute(
        """
        INSERT INTO llm_ingest_stats (agent_id, hour, received_count, rejected_count, last_error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(agent_id, hour) DO UPDATE SET
            received_count = received_count + excluded.received_count,
            rejected_count = rejected_count + excluded.rejected_count,
            last_error = COALESCE(excluded.last_error, llm_ingest_stats.last_error)
        """,
        (agent_id, hour, received, rejected, error),
    )


def receive_llm_call_data(data: Dict[str, Any], db_path: str = "ako_hub.db") -> Dict[str, Any]:
    """
    接收并处理 LLM 调用记录（纯函数，无 Web 依赖）。

    Args:
        data: { agent_id, entry_point, provider, model, prompt_tokens, ... }
        db_path: SQLite 数据库路径

    Returns:
        {"status": "ok"} 或 {"status": "error", "message": str}
    """
    agent_id = data.get("agent_id") or "(unknown)"
    missing = [f for f in ("agent_id", "entry_point") if not data.get(f)]

    try:
        conn = _get_db(db_path)
        try:
            if missing:
                msg = "缺少必需字段: " + ", ".join(missing)
                _bump_ingest_stats(conn, agent_id, rejected=1, error=msg)
                conn.commit()
                return {"status": "error", "message": msg}

            _insert_llm_call(conn, data)
            _bump_ingest_stats(conn, agent_id, received=1)
            conn.commit()
        finally:
            conn.close()

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def get_llm_ingest_stats(db_path: str = "ako_hub.db") -> list[Dict[str, Any]]:
    """查询采集统计（按 agent + 小时聚合）。"""
    conn = _get_db(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM llm_ingest_stats ORDER BY agent_id, hour"
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_llm_calls(db_path: str = "ako_hub.db", limit: int = 100) -> list[Dict[str, Any]]:
    """查询 LLM 调用记录（按写入倒序）。"""
    conn = _get_db(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM llm_calls ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _spoke_registry_agents() -> list[tuple[str, str, str]]:
    """本地 spoke 注册表（registry/workflows.py）agent 型实体清单。

    让"已登记但未部署/未上报心跳"的 Agent 在看板中离线可见；
    registry 导入失败时回退 SEED_AGENTS 常量，保证服务可启动。
    """
    try:
        from registry.workflows import list_all_spokes
        out: list[tuple[str, str, str]] = []
        for s in list_all_spokes():
            if s.get("spoke_type") != "agent":
                continue
            wid = str(s.get("workflow_id", "")).strip()
            if not wid:
                continue
            out.append((wid, str(s.get("display_name") or s.get("name") or wid),
                        str(s.get("agent_type") or "unknown")))
        if out:
            return out
    except Exception:
        pass
    return list(SEED_AGENTS)


def seed_agents_registry(db_path: str = "ako_hub.db") -> None:
    """
    将「本地 spoke 注册表 agent 型清单」幂等登记进 agents_registry（INSERT OR IGNORE），
    并清理注册表幽灵（2026-09-03：已注销/改名且 24h 无心跳的旧行）。

    保留规则：期望清单内行、或 24h 内有活跃心跳的行（双名别名如 AKO_hub ↔ AKO_hub_agent 靠
    dashboard 归一键匹配，别名行有心跳时不可误删）。
    """
    try:
        desired = _spoke_registry_agents()
        conn = _get_db(db_path)
        try:
            for agent_id, display_name, agent_type in desired:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO agents_registry
                        (agent_id, display_name, agent_type, heartbeat_interval)
                    VALUES (?, ?, ?, 30)
                    """,
                    (agent_id, display_name, agent_type),
                )
            # ── 幽灵清理 ──
            desired_ids = {t[0] for t in desired}
            now = datetime.now(timezone.utc)
            rows = conn.execute(
                """
                SELECT a.agent_id, MAX(h.timestamp) AS last_hb
                FROM agents_registry a
                LEFT JOIN heartbeats h ON h.agent_id = a.agent_id
                GROUP BY a.agent_id
                """
            ).fetchall()
            to_delete: list[str] = []
            for r in rows:
                aid = str(r["agent_id"])
                if aid in desired_ids:
                    continue
                last_hb = r["last_hb"]
                if last_hb:
                    try:
                        ts = datetime.fromisoformat(str(last_hb).replace("Z", "+00:00"))
                        if (now - ts).total_seconds() < 24 * 3600:
                            continue  # 活跃心跳中的别名/未登记实体，保留
                    except Exception:
                        pass
                to_delete.append(aid)
            for aid in to_delete:
                conn.execute("DELETE FROM agents_registry WHERE agent_id=?", (aid,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # 看板初始化阶段，种子写入失败不应阻断服务启动
        pass


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
                    h.status, h.cpu_percent, h.memory_mb, h.disk_percent,
                    h.response_time_ms,
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
                seconds_ago = d.get("seconds_ago")
                d["online"] = (seconds_ago if seconds_ago is not None else 999) < 90
                # 展示名回退到 agent_id，避免空名
                d["display_name"] = d.get("display_name") or d.get("agent_id") or ""
                agents.append(d)
        finally:
            conn.close()

        if offline_only:
            agents = [a for a in agents if not a["online"]]

        return {"agents": agents}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}