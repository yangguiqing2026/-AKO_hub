"""
langgraph_master.py — LangGraph 状态机桥接模块

从 master/graph.py 重新导出，并为 dashboard 提供：
- get_graph_state()   → idle / running / error（基于 task_queue 表）
- get_graph_stats()    → {total, done, failed, running, pending}
- get_active_tasks()   → 当前活跃任务列表

命名差异说明（不修改，仅记录）：
  workflows.py      → AKO_quote, AKO_media, AKO_business 等
  task_executor.py  → AKO_quote_agent, AKO_media_agent 等
  两套命名各自内部自洽，分别走 importlib 和 subprocess 调用路径。
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import sqlite3

# ── 重新导出 master.graph 的公开接口 ──────────────────────────────
from master.graph import get_master_graph, build_master_graph, master_graph

__all__ = [
    "get_master_graph",
    "build_master_graph",
    "master_graph",
    "get_graph_state",
    "get_graph_stats",
    "get_active_tasks",
]


# ── 内部：解析 DB 路径（与 hub_api._resolve_paths 一致） ─────────

def _get_db_path() -> str:
    """从 hub.yaml 读取 meta_db 路径，失败则回退默认值。"""
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        root = Path(cfg["sync_root"]).resolve()
        return str(root / cfg.get("meta_db", "age_hub.db"))
    except Exception:
        return str(Path(__file__).resolve().parent.parent / "data" / "age_hub.db")


# ── 公开查询接口 ─────────────────────────────────────────────────

def get_graph_state() -> str:
    """
    读取 task_queue 表判断状态机当前状态。

    Returns:
        "running" — 有 executing 中的任务
        "error"   — 有 failed 任务且无 running
        "idle"    — 无活跃任务
    """
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=3.0)
        conn.row_factory = sqlite3.Row

        running = conn.execute(
            "SELECT COUNT(*) as cnt FROM task_queue WHERE status = 'running'"
        ).fetchone()["cnt"]

        if running > 0:
            return "running"

        failed = conn.execute(
            "SELECT COUNT(*) as cnt FROM task_queue WHERE status = 'failed'"
        ).fetchone()["cnt"]

        if failed > 0:
            return "error"

        return "idle"
    except Exception:
        return "unknown"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_graph_stats() -> Dict[str, int]:
    """返回任务统计: {total, done, failed, running, pending}"""
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=3.0)
        conn.row_factory = sqlite3.Row
        stats = {}
        for status in ("pending", "running", "done", "failed"):
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM task_queue WHERE status = ?", (status,)
            ).fetchone()
            stats[status] = row["cnt"] if row else 0
        stats["total"] = sum(stats.values())
        return stats
    except Exception:
        return {"total": 0, "done": 0, "failed": 0, "running": 0, "pending": 0}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_active_tasks(limit: int = 10) -> List[Dict[str, Any]]:
    """返回当前 pending/running 状态的任务列表。"""
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=3.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT task_id, workflow_id, trigger_agent, status,
                      started_at, finished_at, error_log
               FROM task_queue
               WHERE status IN ('pending', 'running')
               ORDER BY started_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
