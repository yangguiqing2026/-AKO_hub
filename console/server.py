"""
AKO Hub 调度控制台 — FastAPI 后端
SSE 实时推送 + REST API
端口: 7863
"""

import asyncio
import json
import sqlite3
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# ── 路径 ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "ako_hub.db"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# ── 品牌色 ────────────────────────────────────────────────────────
AKO_CREAM = "#EBDAB9"
AKO_GRAY  = "#C3BEB4"
AKO_DARK  = "#231E1C"
AKO_AMBER = "#A08C64"
AKO_GOLD  = "#B99B5F"
AKO_CARD  = "#F7F3E8"


# ═══════════════════════════════════════════════════════════════════
# SSE 管理器
# ═══════════════════════════════════════════════════════════════════

class SSEManager:
    """管理 SSE 客户端连接和广播。"""

    def __init__(self):
        self._queues: list[asyncio.Queue] = []
        self._seq = 0

    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.append(queue)
        try:
            # 发送初始连接确认
            await queue.put({"event": "connected", "data": {}, "ts": time.time()})
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in self._queues:
                self._queues.remove(queue)

    async def broadcast(self, event_type: str, data: dict):
        self._seq += 1
        payload = {"event": event_type, "seq": self._seq, "data": data, "ts": time.time()}
        dead = []
        for q in self._queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            if q in self._queues:
                self._queues.remove(q)


sse = SSEManager()


# ═══════════════════════════════════════════════════════════════════
# 数据库工具
# ═══════════════════════════════════════════════════════════════════

def get_db() -> sqlite3.Connection:
    """获取数据库连接（短连接模式，每次请求新建）。"""
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tasks_table():
    """确保 tasks 表存在。"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'composite',
            title TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress REAL DEFAULT 0.0,
            agent_id TEXT,
            input_data TEXT,
            output_data TEXT,
            error_msg TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            started_at TEXT,
            finished_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def dict_from_row(row: sqlite3.Row) -> dict:
    if row is None:
        return {}
    return dict(row)


# ═══════════════════════════════════════════════════════════════════
# 后台轮询
# ═══════════════════════════════════════════════════════════════════

def _snapshot(conn: sqlite3.Connection) -> dict:
    """获取当前系统快照。"""
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM agents_registry")
        total = cur.fetchone()["cnt"]

        cur = conn.execute("""
            SELECT COUNT(DISTINCT h.agent_id) as cnt
            FROM heartbeats h
            WHERE h.id IN (SELECT MAX(id) FROM heartbeats GROUP BY agent_id)
              AND (strftime('%s','now') - strftime('%s', h.timestamp)) < 120
        """)
        online = cur.fetchone()["cnt"]

        cur = conn.execute("SELECT COUNT(*) as cnt FROM alerts WHERE resolved_at IS NULL")
        alerts = cur.fetchone()["cnt"]

        cur = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status IN ('pending','running')")
        tasks = cur.fetchone()["cnt"]

        cur = conn.execute("""
            SELECT a.agent_id, a.display_name, h.timestamp, h.status,
                   h.cpu_percent, h.memory_mb,
                   CAST((strftime('%s','now') - strftime('%s', h.timestamp)) AS INTEGER) AS seconds_ago
            FROM agents_registry a
            LEFT JOIN heartbeats h ON h.id = (
                SELECT MAX(id) FROM heartbeats WHERE agent_id = a.agent_id
            )
            ORDER BY a.agent_id
        """)
        agents = []
        for row in cur.fetchall():
            d = dict(row)
            ago = d.get("seconds_ago")
            if ago is None:
                d["traffic"] = "gray"
            elif ago <= 120:
                d["traffic"] = "green"
            elif ago <= 600:
                d["traffic"] = "yellow"
            else:
                d["traffic"] = "red"
            agents.append(d)

        return {
            "total": total,
            "online": online,
            "alerts": alerts,
            "active_tasks": tasks,
            "agents": agents,
            "ts": datetime.now().isoformat(),
        }
    except Exception:
        return {"total": 0, "online": 0, "alerts": 0, "active_tasks": 0, "agents": [], "ts": ""}


async def poll_db_loop():
    """每 3 秒轮询数据库并广播变化。"""
    conn = sqlite3.connect(str(DB_PATH), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    last_hash = ""

    while True:
        try:
            snap = _snapshot(conn)
            h = hash(json.dumps(snap, sort_keys=True, default=str))
            if str(h) != last_hash:
                last_hash = str(h)
                await sse.broadcast("snapshot", snap)
        except Exception:
            pass
        await asyncio.sleep(3)


# ═══════════════════════════════════════════════════════════════════
# FastAPI 应用
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_tasks_table()
    poller = asyncio.create_task(poll_db_loop())
    yield
    poller.cancel()


app = FastAPI(title="AKO Hub 调度控制台", version="1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# ── 页面 ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ── SSE 流 ─────────────────────────────────────────────────────────

@app.get("/api/stream")
async def api_stream():
    return StreamingResponse(
        sse.subscribe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 系统状态 ───────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    conn = get_db()
    try:
        snap = _snapshot(conn)
        return snap
    finally:
        conn.close()


# ── Agent 列表 ─────────────────────────────────────────────────────

@app.get("/api/agents")
async def api_agents():
    conn = get_db()
    try:
        cur = conn.execute("""
            SELECT a.agent_id, a.display_name, a.agent_type,
                   h.timestamp AS last_heartbeat, h.status,
                   h.cpu_percent, h.memory_mb, h.disk_percent,
                   h.task_total, h.task_success, h.task_failed,
                   h.last_task, h.last_task_status,
                   CAST((strftime('%s','now') - strftime('%s', h.timestamp)) AS INTEGER) AS seconds_ago
            FROM agents_registry a
            LEFT JOIN heartbeats h ON h.id = (
                SELECT MAX(id) FROM heartbeats WHERE agent_id = a.agent_id
            )
            ORDER BY a.agent_id
        """)
        agents = []
        for row in cur.fetchall():
            d = dict(row)
            ago = d.get("seconds_ago")
            if ago is None:
                d["traffic"] = "gray"
            elif ago <= 120:
                d["traffic"] = "green"
            elif ago <= 600:
                d["traffic"] = "yellow"
            else:
                d["traffic"] = "red"
            agents.append(d)
        return {"agents": agents, "count": len(agents)}
    finally:
        conn.close()


# ── 告警 ───────────────────────────────────────────────────────────

@app.get("/api/alerts")
async def api_alerts(resolved: bool = False):
    conn = get_db()
    try:
        if resolved:
            cur = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 50")
        else:
            cur = conn.execute("SELECT * FROM alerts WHERE resolved_at IS NULL ORDER BY created_at DESC")
        return {"alerts": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@app.post("/api/alerts/{alert_id}/ack")
async def api_ack_alert(alert_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── 日志 ───────────────────────────────────────────────────────────

@app.get("/api/logs")
async def api_logs(
    agent: Optional[str] = None,
    level: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=10, le=500),
):
    conn = get_db()
    try:
        conditions = []
        params = []
        if agent:
            conditions.append("l.agent_id = ?")
            params.append(agent)
        if level:
            conditions.append("l.level = ?")
            params.append(level.upper())
        if search:
            conditions.append("l.message LIKE ?")
            params.append(f"%{search}%")

        where = " AND ".join(conditions) if conditions else "1=1"

        cur = conn.execute(f"""
            SELECT l.*, a.display_name
            FROM logs l
            LEFT JOIN agents_registry a ON l.agent_id = a.agent_id
            WHERE {where}
            ORDER BY l.timestamp DESC
            LIMIT ?
        """, params + [limit])
        return {"logs": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


# ── 任务 ───────────────────────────────────────────────────────────

@app.get("/api/tasks")
async def api_tasks(status: Optional[str] = None, limit: int = Query(default=50, ge=10, le=200)):
    conn = get_db()
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        return {"tasks": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@app.post("/api/tasks")
async def api_create_task(request: Request):
    body = await request.json()
    title = body.get("title", "未命名任务")
    task_type = body.get("task_type", "composite")
    intent = body.get("intent", "")
    agent_id = body.get("agent_id")
    input_data = json.dumps(body.get("input_data", {}), ensure_ascii=False)

    import uuid
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO tasks (task_id, task_type, title, status, agent_id, input_data)
            VALUES (?, ?, ?, 'pending', ?, ?)
        """, (task_id, task_type, title, agent_id, input_data))
        conn.commit()
        return {"ok": True, "task_id": task_id}
    finally:
        conn.close()


# ── 同步状态 ───────────────────────────────────────────────────────

def _check_sync_status() -> dict:
    """检查百度云盘同步状态。"""
    sync_root = Path("E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub")
    online = sync_root.exists()
    if online:
        # 检查最近修改的文件
        try:
            latest = max(sync_root.rglob("*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0, default=None)
            latest_ts = datetime.fromtimestamp(latest.stat().st_mtime).isoformat() if latest else None
        except Exception:
            latest_ts = None
    else:
        latest_ts = None
    return {
        "online": online,
        "path": str(sync_root) if online else None,
        "latest_file_ts": latest_ts,
        "ts": datetime.now().isoformat(),
    }


@app.get("/api/sync-status")
async def api_sync_status():
    return _check_sync_status()


# ── 配置 ───────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config():
    """返回当前系统配置摘要。"""
    hub_yaml = PROJECT_ROOT / "config" / "hub.yaml"
    env_file = PROJECT_ROOT / "config" / ".env"
    return {
        "db_path": str(DB_PATH),
        "hub_yaml_exists": hub_yaml.exists(),
        "env_exists": env_file.exists(),
        "project_root": str(PROJECT_ROOT),
        "port": 7863,
        "agents_from_db": True,
        "brand": {
            "cream": AKO_CREAM,
            "gray": AKO_GRAY,
            "dark": AKO_DARK,
            "amber": AKO_AMBER,
            "gold": AKO_GOLD,
            "card": AKO_CARD,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"AKO Hub 调度控制台启动: http://localhost:7863")
    print(f"DB: {DB_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=7863, log_level="info")
