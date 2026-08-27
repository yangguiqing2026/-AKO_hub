"""
hub/dashboard/app.py
AKO Dashboard 后端 — FastAPI + WebSocket 实时推送 + 完整运营台

定位：AKO Hub 的唯一 Web 入口（完整运营台）。
  1. 看板（只读）：Agent 接入状态、阶段、质检分数（来自 registry + pipeline_state.json）。
  2. 任务输入：POST /api/tasks 提交任务（内部转发 hub_api.submit_task）。
  3. 任务管理：GET /api/tasks 读任务队列表。
  4. 健康巡检：GET /api/health/agents + /api/health/alerts（读 ako_hub.db 心跳库）。
  5. Agent 注册中心：GET/POST/DELETE /api/spokes + GET /api/http-agents。
  6. 事件流：GET /api/events（读 events/{pending,completed,failed}）。
  7. 知识库与文件：GET /api/knowledge-bases + GET /api/files。
  8. 实时推送：WebSocket /ws，监听 pipeline_state.json 变化主动广播。

用法:
    python dashboard/app.py                 # 直接用脚本路径启动
    python -m dashboard.app                 # 或作为包启动
    python cli.py ui                        # 经 cli 转发（指向本文件）
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

# ── 路径与常量 ───────────────────────────────────────────────────

AKO_HUB_ROOT = Path(__file__).resolve().parent.parent
if str(AKO_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(AKO_HUB_ROOT))

AKO_ROOT = Path(os.getenv("AKO_ROOT", "D:/AKO"))
STATE_FILE = AKO_ROOT / "pipeline_state.json"
STATIC_DIR = Path(__file__).parent / "static"

# 心跳监控库、事件流、HTTP 注册中心文件
HEARTBEAT_DB = AKO_HUB_ROOT / "ako_hub.db"
# 事件总线统一位置：events/bus.py 的 AKO_ROOT = 项目根 D:\AKO
# （原指向 AKO_hub/events，与总线写入目录漂移，看板恒读空）
EVENTS_ROOT = AKO_HUB_ROOT.parent / "events"
HTTP_AGENTS_FILE = AKO_HUB_ROOT / "registry" / "http_registered_agents.json"
OPERATOR_CAPS_FILE = AKO_HUB_ROOT / "config" / "operator_capabilities.yaml"
ROUTING_RULES_FILE = AKO_HUB_ROOT / "config" / "routing_rules.yaml"
EMPLOYEE_ACCESS_FILE = AKO_HUB_ROOT / "config" / "employee_access.yaml"
GOVERNOR_ACCESS_FILE = AKO_HUB_ROOT / "config" / "governor_access.yaml"
AGENT_NAMES_FILE = AKO_HUB_ROOT / "config" / "agent_names.yaml"

app = FastAPI(title="AKO Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """HTML 响应禁用缓存，避免前端改版后浏览器仍显示旧页面。"""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── 路径解析（与 hub_api 保持一致） ───────────────────────────────

def _resolve_paths() -> Dict[str, str]:
    try:
        import yaml
        cfg_path = AKO_HUB_ROOT / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        root = Path(cfg["sync_root"]).resolve()
        return {
            "sync_root": str(root),
            "db_path": str(root / cfg.get("meta_db", "age_hub.db")),
            "chroma_root": str(root / cfg.get("chroma_root", "chroma_db")),
            "file_root": str(root / cfg.get("file_root", "files")),
        }
    except Exception:
        return {
            "sync_root": str(AKO_HUB_ROOT),
            "db_path": str(AKO_HUB_ROOT / "age_hub.db"),
            "chroma_root": str(AKO_HUB_ROOT / "chroma_db"),
            "file_root": str(AKO_HUB_ROOT / "files"),
        }


# ── 看板状态（注册表 → Agent 清单 + 状态文件 → 详情） ────────────

def _load_registry() -> dict:
    try:
        from registry.workflows import list_all_spokes
        spokes = list_all_spokes()
        return {s["workflow_id"]: s for s in spokes if s.get("spoke_type") == "agent"}
    except Exception:
        return {}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _ensure_state_file() -> dict:
    state = _load_state()
    if not STATE_FILE.exists():
        registry = _load_registry()
        agents = {}
        for wf_id, info in registry.items():
            agents[wf_id] = {
                "stage": "S1_init",
                "name": info.get("name", wf_id),
                "state": "S1_init",
                "qc_score": None,
                "veto_fails": [],
                "updated_at": None,
            }
        state = {"agents": agents}
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
    return state


def _heartbeat_status_map() -> Dict[str, Dict[str, Any]]:
    """返回 agent_id -> 心跳状态字段 (online/last_heartbeat/display_name/agent_type/资源)。"""
    data = _health_agents()
    mapping: Dict[str, Dict[str, Any]] = {}
    for a in data.get("agents", []):
        agent_id = a.get("agent_id")
        if agent_id:
            mapping[agent_id] = a
    return mapping


def _norm_agent_key(agent_id: str) -> str:
    """归一化键：AKO_xxx_agent 与 AKO_xxx 视为同一实体（registry 键 ↔ hub 键）。"""
    return agent_id[:-6] if agent_id.endswith("_agent") else agent_id


def _merged_state() -> dict:
    """合并总控台 Agent 状态（去重归一，registry 登记实体为权威骨架）。

    去重规则：
    1. registry 已登记实体（35）为骨架，心跳按归一键叠加在线状态；
    2. hub 内置 spoke（chat/reports/form_extractor/工作流/geo）保留但标记 builtin；
    3. 心跳孤儿（未登记且非内置，如已注销的 AKO_review_agent）丢弃，不再出现。
    """
    state = _ensure_state_file()
    ps_agents = state.get("agents", {})
    names = _load_agent_names()
    hb = _heartbeat_status_map()
    hb_norm: Dict[str, Dict[str, Any]] = {}
    for k, v in hb.items():
        hb_norm.setdefault(_norm_agent_key(k), v)

    agents: Dict[str, Any] = {}

    for m in _registry_agents():
        aid = m.get("agent_id", "")
        if not aid:
            continue
        nk = _norm_agent_key(aid)
        display = names.get(aid) or names.get(nk) or m.get("human_readable_name", aid)
        hbe = hb_norm.get(nk, {})
        ps = ps_agents.get(aid) or ps_agents.get(nk) or {}
        agents[aid] = {
            "stage": ps.get("stage", "S1_init"),
            "name": display,
            "state": ps.get("state", "S1_init"),
            "qc_score": ps.get("qc_score"),
            "veto_fails": ps.get("veto_fails", []),
            "updated_at": ps.get("updated_at"),
            "agent_id": aid,
            "display_name": display,
            "domain": m.get("domain", ""),
            "quality_tier": m.get("quality_tier", "C"),
            "deployed_env": m.get("deployed_env", "staging"),
            "lifecycle_state": m.get("lifecycle_state", "staging"),
            "online": bool(hbe.get("online")),
            "last_heartbeat": hbe.get("last_heartbeat"),
            "agent_type": hbe.get("agent_type"),
            "cpu_percent": hbe.get("cpu_percent"),
            "memory_mb": hbe.get("memory_mb"),
            "last_task_status": hbe.get("last_task_status"),
        }

    # hub 内置 spoke：非独立实体，但保留在总控台（与 registry 归一键去重）
    for wf_id, info in (_load_registry() or {}).items():
        nk = _norm_agent_key(wf_id)
        if any(_norm_agent_key(a) == nk for a in agents):
            continue
        hbe = hb_norm.get(nk, {})
        agents[wf_id] = {
            "stage": "S1_init",
            "name": info.get("name", wf_id),
            "state": "S1_init",
            "qc_score": None,
            "veto_fails": [],
            "updated_at": None,
            "agent_id": wf_id,
            "display_name": info.get("name", wf_id),
            "builtin": True,
            "online": bool(hbe.get("online")),
            "last_heartbeat": hbe.get("last_heartbeat"),
            "agent_type": hbe.get("agent_type"),
            "cpu_percent": hbe.get("cpu_percent"),
            "memory_mb": hbe.get("memory_mb"),
            "last_task_status": hbe.get("last_task_status"),
        }

    return {"agents": agents}


# ── 任务管理（转发 hub_api） ─────────────────────────────────────

def _list_tasks(limit: int = 100) -> Dict[str, Any]:
    """读取 task_queue 表，返回任务列表。"""
    from core.hub_db import HubDB

    paths = _resolve_paths()
    db = HubDB(paths["db_path"])
    try:
        db.connect()
        db.init_schema()
        rows = db.fetchall(
            "SELECT * FROM task_queue ORDER BY COALESCE(started_at, '') DESC LIMIT ?",
            (limit,),
        )
        return {"tasks": rows}
    except Exception as e:
        return {"tasks": [], "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()


# ── 健康巡检（心跳监控库 ako_hub.db） ────────────────────────────

def _init_heartbeat_db() -> None:
    """确保心跳库表结构存在（幂等）。"""
    try:
        from heartbeat.heartbeat_server import init_heartbeat_db
        init_heartbeat_db(str(HEARTBEAT_DB))
    except Exception:
        pass


def _health_agents() -> Dict[str, Any]:
    """查询各 Agent 心跳与在线状态。"""
    _init_heartbeat_db()
    try:
        from heartbeat.heartbeat_receiver import get_agents_status
        return get_agents_status(str(HEARTBEAT_DB))
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}", "agents": []}


def _health_alerts(limit: int = 100) -> List[Dict[str, Any]]:
    """读取告警表。"""
    _init_heartbeat_db()
    try:
        conn = sqlite3.connect(str(HEARTBEAT_DB))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


# ── Agent 注册中心 ───────────────────────────────────────────────

def _list_spokes(spoke_type: str = "") -> List[Dict[str, Any]]:
    from hub_api import list_spokes
    return list_spokes(spoke_type=spoke_type)


def _http_registered_agents() -> Dict[str, Any]:
    if HTTP_AGENTS_FILE.exists():
        try:
            return json.loads(HTTP_AGENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


# ── 事件流（events/{pending,completed,failed}） ──────────────────

def _list_events(limit: int = 100) -> Dict[str, Any]:
    """读取事件总线三个目录，返回最新事件与计数。"""
    result: Dict[str, Any] = {"pending": [], "completed": [], "failed": [], "counts": {}}
    for key in ("pending", "completed", "failed"):
        d = EVENTS_ROOT / key
        if not d.exists():
            result["counts"][key] = 0
            continue
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        result["counts"][key] = len(files)
        bucket = result[key]
        for f in files[:limit]:
            try:
                bucket.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return result


# ── WebSocket 连接池 ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self.push_state(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def push_state(self, websocket: WebSocket):
        await websocket.send_json({"type": "full_state", "data": _merged_state()})


manager = ConnectionManager()


# ── 看板路由 ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    landing_file = STATIC_DIR / "landing.html"
    if landing_file.exists():
        return landing_file.read_text(encoding="utf-8")
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "<h1>AKO Dashboard</h1><p>Frontend not built yet.</p>"


@app.get("/api/state")
async def get_state():
    return _merged_state()


@app.get("/api/agents")
async def get_agents():
    return _merged_state().get("agents", {})


# ── 健康巡检路由 ─────────────────────────────────────────────────

@app.get("/api/health/agents")
async def health_agents():
    return _health_agents()


@app.get("/api/health/alerts")
async def health_alerts():
    return {"alerts": _health_alerts()}


# ── Agent 注册中心路由 ───────────────────────────────────────────

@app.get("/api/spokes")
async def get_spokes(spoke_type: str = ""):
    return {"spokes": _list_spokes(spoke_type)}


@app.post("/api/spokes")
async def create_spoke(payload: Dict[str, Any]):
    """注册一个 Spoke（转发 hub_api.register_spoke_api）。"""
    from hub_api import register_spoke_api

    required = ["workflow_id", "name", "spoke_type", "entry_module", "source_dir"]
    missing = [k for k in required if not str(payload.get(k, "")).strip()]
    if missing:
        return {"status": "error", "message": f"缺少必填字段: {', '.join(missing)}"}

    kb_ids = payload.get("required_kb_ids") or []
    if isinstance(kb_ids, str):
        kb_ids = [x.strip() for x in kb_ids.split(",") if x.strip()]

    return register_spoke_api(
        workflow_id=str(payload["workflow_id"]).strip(),
        name=str(payload["name"]).strip(),
        spoke_type=str(payload["spoke_type"]).strip(),
        entry_module=str(payload["entry_module"]).strip(),
        source_dir=str(payload["source_dir"]).strip(),
        entry_function=str(payload.get("entry_function", "run") or "run").strip(),
        required_kb_ids=kb_ids,
        output_dir=str(payload.get("output_dir", "")).strip(),
        description=str(payload.get("description", "")).strip(),
    )


@app.delete("/api/spokes/{workflow_id}")
async def delete_spoke(workflow_id: str):
    """移除一个已注册的 Spoke。"""
    from hub_api import remove_spoke
    return remove_spoke(workflow_id)


@app.get("/api/http-agents")
async def http_agents():
    """返回 HTTP 注册中心登记的 Agent（含完整 agent_card）。"""
    return _http_registered_agents()


# ── 事件流路由 ───────────────────────────────────────────────────

@app.get("/api/events")
async def get_events(limit: int = 100):
    return _list_events(limit)


# ── 知识库与文件路由 ─────────────────────────────────────────────

@app.get("/api/knowledge-bases")
async def knowledge_bases():
    """列出知识库。"""
    try:
        from hub_api import list_knowledge_bases
        return {"knowledge_bases": list_knowledge_bases()}
    except Exception as e:
        return {"knowledge_bases": [], "error": f"{type(e).__name__}: {e}"}


@app.get("/api/files")
async def get_files(project_tag: str = "", limit: int = 50):
    """浏览已注册文件。"""
    from hub_api import list_files
    return list_files(project_tag=project_tag, limit=limit)


# ── 任务路由（Hub 唯一 Web 任务入口） ─────────────────────────────

@app.post("/api/tasks")
def create_task(payload: Dict[str, Any]):
    """
    提交任务。请求体示例：
        {"intent": "结构计算", "workflow_id": "", "project_tag": "taoli"}
    二者至少提供一个（intent 走意图路由，workflow_id 走显式指定）。
    内部转发 hub_api.submit_task，返回最终任务状态。
    """
    from hub_api import submit_task

    intent = payload.get("intent", "")
    workflow_id = payload.get("workflow_id", "")
    project_tag = payload.get("project_tag", "")
    trigger = payload.get("trigger", "dashboard")

    task_payload: Dict[str, Any] = {}
    if workflow_id:
        task_payload["workflow_id"] = workflow_id
    if intent:
        task_payload["intent"] = intent
    if project_tag:
        task_payload["project_tag"] = project_tag

    if not task_payload:
        return {"status": "error", "message": "缺少 intent 或 workflow_id"}

    # submit_task 会触发 langgraph 图执行，可能较慢；FastAPI 对同步 def 自动放线程池执行
    return submit_task(task_payload, trigger=trigger)


@app.get("/api/tasks")
def list_tasks():
    """返回任务队列（最近 100 条）。"""
    return _list_tasks()


# ── AKO_agent工作台（Operator View） ─────────────────────────────

def _load_operator_caps() -> Dict[str, Any]:
    """读取 config/operator_capabilities.yaml。失败返回空配置。"""
    if OPERATOR_CAPS_FILE.exists():
        try:
            import yaml
            with open(OPERATOR_CAPS_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg
        except Exception:
            pass
    return {"capabilities": [], "pipelines": [], "templates": []}


def _workorder_db() -> Any:
    """返回已初始化 schema 的 HubDB 实例（调用方负责 close）。"""
    from core.hub_db import HubDB

    paths = _resolve_paths()
    db = HubDB(paths["db_path"])
    db.connect()
    db.init_schema()
    return db


def _generate_wo_id() -> str:
    """生成人工工单 ID：WO-YYYYMMDD-HHMMSS-xxxx。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"WO-{ts}-{uuid.uuid4().hex[:4].upper()}"


def _spoke_deployable(workflow_id: str) -> bool:
    """判断 workflow_id 对应 Agent 的 source_dir 是否已部署（目录存在）。"""
    from registry.workflows import get_spoke_by_id

    spoke = get_spoke_by_id(workflow_id)
    if not spoke:
        return False
    src = spoke.get("source_dir", "")
    if not src:
        return False
    return Path(src).exists()


def _load_employee_access() -> List[Dict[str, str]]:
    """读取员工访问控制表（姓名 + 6 位数字指纹）。"""
    if EMPLOYEE_ACCESS_FILE.exists():
        try:
            import yaml
            with open(EMPLOYEE_ACCESS_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("employees", []) or []
        except Exception:
            pass
    return []


@app.post("/api/auth/login")
async def auth_login(payload: Dict[str, Any]):
    """
    员工指纹登录校验（role=operator）。

    认证链路（2026-08-27 全面切换身份认证层，白皮书 §13）：
    1. 优先经 AKO_identity_service /verify 逐人校验（身份注册册为唯一法源）
    2. 未命中时回退本地盐值+哈希员工表（无明文）
    """
    fp = str(payload.get("fingerprint", "") or "").strip()
    if not fp.isdigit() or len(fp) != 6:
        return {"status": "fail", "message": "请输入 6 位数字指纹"}

    human = await _verify_human_via_identity_service(fp)
    if human:
        return {"status": "ok", "name": human.get("name", ""), "role": "operator",
                "human_id": human.get("human_id", ""), "via": "identity_service"}

    import hashlib
    for emp in _load_employee_access():
        salt = str(emp.get("salt", ""))
        expect = str(emp.get("fingerprint_hash", ""))
        if salt and expect and hashlib.sha256((salt + fp).encode()).hexdigest() == expect:
            return {"status": "ok", "name": emp.get("name", ""), "role": "operator", "via": "local_hash"}
    return {"status": "fail", "message": "指纹不匹配，无访问权限"}


async def _verify_human_via_identity_service(fp: str) -> Optional[Dict[str, str]]:
    """经身份认证层逐人校验指纹（人类身份注册册为唯一法源）。

    从本地降级副本读取 human_id 列表，逐个 POST /api/v1/identity/verify。
    命中返回 {human_id, name, role}，否则 None。
    """
    import httpx
    reg = Path(r"D:\AKO\AKO_identity_service\config\human_identities.yaml")
    if not reg.exists():
        return None
    try:
        import yaml
        humans = (yaml.safe_load(reg.read_text(encoding="utf-8-sig")) or {}).get("human_identities", []) or []
    except Exception:
        return None
    for h in humans:
        if h.get("status") != "active":
            continue
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post("http://127.0.0.1:5025/api/v1/identity/verify", json={
                    "actor_type": "human",
                    "actor_id": h.get("human_id", ""),
                    "operation": "authorize_wo",
                    "fingerprint": fp,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "nonce": f"dash-{int(time.time())}-{h.get('human_id', 'x')[-4:]}",
                })
                data = resp.json()
        except Exception:
            continue
        if data.get("verified") is True:
            return {"human_id": h.get("human_id", ""), "name": h.get("name", ""),
                    "role": h.get("role", "")}
    return None


def _load_governor_access() -> List[Dict[str, str]]:
    """读取老板访问控制表（姓名 + 6 位数字指纹）。"""
    if GOVERNOR_ACCESS_FILE.exists():
        try:
            import yaml
            with open(GOVERNOR_ACCESS_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("governors", []) or []
        except Exception:
            pass
    return []


def _load_agent_names() -> Dict[str, str]:
    """读取 Agent 中英文名称对照表。"""
    if AGENT_NAMES_FILE.exists():
        try:
            import yaml
            with open(AGENT_NAMES_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return {str(k): str(v) for k, v in (cfg.get("agents", {}) or {}).items()}
        except Exception:
            pass
    return {}


@app.post("/api/auth/governor-login")
async def governor_login(payload: Dict[str, Any]):
    """
    老板指纹登录校验（role=governor）。

    认证链路（2026-08-27 全面切换身份认证层）：
    1. AKO_identity_service /verify 逐人校验（身份注册册唯一法源）
    2. 命中者须在 governor allowlist（human_id 白名单，无凭证存储）
    """
    fp = str(payload.get("fingerprint", "") or "").strip()
    if not fp.isdigit() or len(fp) != 6:
        return {"status": "fail", "message": "请输入 6 位数字指纹"}

    human = await _verify_human_via_identity_service(fp)
    if not human:
        return {"status": "fail", "message": "指纹不匹配，无访问权限"}

    for g in _load_governor_access():
        if g.get("human_id") == human.get("human_id"):
            return {"status": "ok", "name": g.get("name") or human.get("name", ""),
                    "role": "governor", "human_id": human.get("human_id")}
    return {"status": "fail", "message": f"{human.get('name', '该人员')} 已在身份册登记但无治理指挥室权限"}


_INTENT_ROUTER = None


def _get_intent_router():
    """懒加载 IntentRouter 单例（避免每次请求重复初始化）。"""
    global _INTENT_ROUTER
    if _INTENT_ROUTER is None:
        from router.intent_router import IntentRouter
        _INTENT_ROUTER = IntentRouter()
    return _INTENT_ROUTER


@app.post("/api/intent/parse")
async def intent_parse(payload: Dict[str, Any]):
    """
    自然语言意图识别（调用后端 IntentRouter）。
    返回目标 agent_id + 置信度，并映射到员工台能力目录（若命中）。
    """
    text = str(payload.get("text", "") or "").strip()
    if not text:
        return {"status": "fail", "message": "请输入需求描述"}

    try:
        router = _get_intent_router()
        result = router.parse_intent(text)
    except Exception as e:
        return {"status": "fail", "message": f"意图识别服务异常: {e}"}

    # 映射到员工台能力目录（operator_capabilities.yaml 的 workflow_id）
    caps = (_load_operator_caps() or {}).get("capabilities", [])
    matched_cap = None
    for c in caps:
        if c.get("workflow_id") == result.get("agent_id"):
            matched_cap = c
            break

    out = {
        "status": "ok",
        "intent": result.get("intent", ""),
        "agent_id": result.get("agent_id", ""),
        "confidence": result.get("confidence", 0.0),
        "dependencies": result.get("dependencies", []),
        "estimated_time": result.get("estimated_time", 0),
        "matched": matched_cap is not None,
    }
    if matched_cap:
        out["workflow_id"] = matched_cap.get("workflow_id")
        out["display"] = matched_cap.get("display")
    return out


@app.get("/landing", response_class=HTMLResponse)
async def landing():
    """落地页（默认入口）。"""
    f = STATIC_DIR / "landing.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<h1>AKO</h1><p>landing.html 尚未构建。</p>"


@app.get("/operator", response_class=HTMLResponse)
async def operator():
    """AKO_agent工作台页面入口（员工视图，role=operator）。"""
    f = STATIC_DIR / "operator.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<h1>AKO_agent工作台</h1><p>operator.html 尚未构建。</p>"


@app.get("/governor", response_class=HTMLResponse)
async def governor():
    """AKO 治理指挥室页面入口（老板视图，role=governor）。"""
    f = STATIC_DIR / "governor.html"
    html = f.read_text(encoding="utf-8") if f.exists() else "<h1>AKO 治理指挥室</h1><p>governor.html 尚未构建。</p>"
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.get("/heatmap", response_class=HTMLResponse)
async def heatmap_page():
    """AKO 热力总览独立页（全部已登记实体卡片，三色分层）。"""
    f = STATIC_DIR / "heatmap.html"
    html = f.read_text(encoding="utf-8") if f.exists() else "<h1>AKO 热力总览</h1><p>heatmap.html 尚未构建。</p>"
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ── 治理拓扑（三层同心圆 + 实际连接） ─────────────────────────────

# 分层规则（域→层）：基座域→知识层，运维域→运维层，其余→工具层；hub 为圆心不入环
_DOMAIN_TO_LAYER = {"基座域": "知识层", "运维域": "运维层"}
# 两套配色：拓扑图（同心圆环/节点）与热力总览（卡片）各自独立三色
_LAYER_COLORS = {"知识层": "#B99B5F", "运维层": "#A08C64", "工具层": "#7A9E7E"}
_HEATMAP_COLORS = {"知识层": "#D4A574", "运维层": "#EBDAB9", "工具层": "#A08C64"}
_LAYERS_FILE = AKO_HUB_ROOT / "config" / "agent_layers.yaml"


def _layer_members() -> Dict[str, List[str]]:
    """读取分层名单（AKO_studio 指定名单优先）。"""
    if _LAYERS_FILE.exists():
        try:
            import yaml
            cfg = yaml.safe_load(_LAYERS_FILE.read_text(encoding="utf-8-sig")) or {}
            layers = cfg.get("layers", {}) or {}
            return {str(k): [str(x) for x in (v or [])]
                    for k, v in layers.items() if k in _LAYER_COLORS}
        except Exception:
            pass
    return {}


def _registry_agents() -> List[Dict[str, Any]]:
    """从 AKO_registry_agent 拉取全部已登记实体的完整 manifest（本地降级：空列表）。

    /agents 仅返回摘要（无 domain/quality_tier），故逐实体 GET /agents/{id}
    取完整 manifest（registry 内存缓存，本地毫秒级）。
    """
    import httpx
    try:
        with httpx.Client(timeout=6) as client:
            data = client.get("http://127.0.0.1:5024/ako/api/v1/registry/agents").json()
            agents = data.get("agents", data) if isinstance(data, dict) else data
            if isinstance(agents, dict):
                ids = list(agents.keys())
            else:
                ids = [a.get("agent_id", "") for a in agents if isinstance(a, dict)]
            full = []
            for aid in ids:
                if not aid:
                    continue
                try:
                    m = client.get(f"http://127.0.0.1:5024/ako/api/v1/registry/agents/{aid}").json()
                    manifest = m.get("manifest", m) if isinstance(m, dict) else m
                    if isinstance(manifest, dict) and manifest.get("agent_id"):
                        full.append(manifest)
                except Exception:
                    continue
            return full
    except Exception:
        return []


def _agent_layer(agent_id: str, domain: str) -> str:
    if agent_id in ("AKO_hub_agent", "AKO_hub"):
        return "圆心"
    for layer, members in _layer_members().items():
        if agent_id in members or agent_id.replace("_agent", "") in members:
            return layer
    return _DOMAIN_TO_LAYER.get(domain, "工具层")


def _topology_edges() -> List[Dict[str, str]]:
    p = AKO_HUB_ROOT / "config" / "agent_edges.yaml"
    if not p.exists():
        return []
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
        return [{"from": e["from"], "to": e["to"], "type": e.get("type", "data")}
                for e in (cfg.get("edges", []) or [])]
    except Exception:
        return []


@app.get("/api/governance/topology")
async def governance_topology():
    """
    老板看板拓扑数据源：
    - rings: 三层同心圆（知识层/运维层/工具层），hub 为圆心
    - 每实体含 online/lifecycle_state/quality_tier/domain/layer/color
    - edges: 实际连接 = 心跳边（在线实体→hub）+ agent_edges.yaml 静态边（仅双方已注册）
    """
    registry = _registry_agents()
    hb = _heartbeat_status_map()
    names = _load_agent_names()

    by_id: Dict[str, Dict[str, Any]] = {}
    for m in registry:
        aid = m.get("agent_id", "")
        if not aid:
            continue
        # 统一 hub 双名（注册键 AKO_hub_agent ↔ 心跳键 AKO_hub）
        if aid == "AKO_hub_agent":
            hb_status = hb.get("AKO_hub") or hb.get(aid) or {}
        else:
            hb_status = hb.get(aid) or {}
        layer = _agent_layer(aid, m.get("domain", ""))
        by_id[aid] = {
            "agent_id": aid,
            "name_zh": names.get(aid) or names.get(aid.replace("_agent", "")) or m.get("human_readable_name", aid),
            "domain": m.get("domain", ""),
            "layer": layer,
            "color": _LAYER_COLORS.get(layer, "#A08C64"),
            "heatmap_color": _HEATMAP_COLORS.get(layer, "#A08C64"),
            "lifecycle_state": m.get("lifecycle_state", "staging"),
            "quality_tier": m.get("quality_tier", "C"),
            "deployed_env": m.get("deployed_env", "staging"),
            "status": m.get("status", "standby"),
            "online": bool(hb_status.get("online")),
            "last_heartbeat": hb_status.get("last_heartbeat"),
            "cpu_percent": hb_status.get("cpu_percent"),
        }

    rings: Dict[str, List[Dict[str, Any]]] = {"知识层": [], "运维层": [], "工具层": []}
    hub = None
    for a in by_id.values():
        if a["layer"] == "圆心":
            hub = a
        else:
            rings.setdefault(a["layer"], []).append(a)

    # 心跳边：所有在线实体 → hub
    edges: List[Dict[str, Any]] = []
    seen: set = set()
    for a in by_id.values():
        if a["online"] and a["layer"] != "圆心":
            edges.append({"from": a["agent_id"], "to": "AKO_hub_agent",
                          "type": "heartbeat", "online": True})
            seen.add((a["agent_id"], "AKO_hub_agent"))
    # 静态边（双方已注册才画）
    for e in _topology_edges():
        f, t = e["from"], e["to"]
        if f in by_id and t in by_id and (f, t) not in seen:
            edges.append({"from": f, "to": t, "type": e["type"],
                          "online": by_id[f]["online"] and by_id[t]["online"]})
            seen.add((f, t))

    return {
        "hub": hub,
        "rings": rings,
        "layer_colors": _LAYER_COLORS,
        "heatmap_colors": _HEATMAP_COLORS,
        "edges": edges,
        "counts": {k: len(v) for k, v in rings.items()},
        "total": len(by_id),
        "online_total": sum(1 for a in by_id.values() if a["online"]),
    }


@app.get("/api/capabilities")
async def capabilities():
    """
    聚合能力目录：config/operator_capabilities.yaml + registry + 心跳在线状态。
    返回 [{workflow_id, display, display_agent, name, entry_module, category,
            sla_seconds, description, online, cpu_percent, last_task_status, deployable}]
    """
    cfg = _load_operator_caps()
    caps = cfg.get("capabilities", [])

    hb_map = _heartbeat_status_map()
    registry = _load_registry()

    out: List[Dict[str, Any]] = []
    for cap in caps:
        wid = cap.get("workflow_id", "")
        spoke = registry.get(wid, {})
        hb = hb_map.get(wid, {})
        out.append({
            "workflow_id": wid,
            "display": cap.get("display", wid),
            "display_agent": cap.get("display_agent", wid),
            "category": cap.get("category", ""),
            "sla_seconds": cap.get("sla_seconds"),
            "description": cap.get("description", spoke.get("description", "")),
            "entry_module": spoke.get("entry_module", ""),
            "name": spoke.get("name", wid),
            "status": spoke.get("status", "registered"),
            "online": bool(hb.get("online")),
            "cpu_percent": hb.get("cpu_percent"),
            "memory_mb": hb.get("memory_mb"),
            "last_task_status": hb.get("last_task_status"),
            "deployable": _spoke_deployable(wid),
        })
    return {"capabilities": out}


@app.get("/api/pipelines")
async def pipelines():
    """返回快捷调用流水线配置。"""
    cfg = _load_operator_caps()
    return {"pipelines": cfg.get("pipelines", []), "templates": cfg.get("templates", [])}


@app.get("/api/governance/overview")
async def governance_overview():
    """
    治理指挥室数据聚合（角色裁剪：role=governor）。

    仅返回治理/监控维度数据（Agent 健康、告警、审计事件、Hub 节点、立法进度），
    不含员工工单提交、能力目录等操作细节 —— 与 /api/capabilities、/api/workorders 分离，
    落实《AKO 双层看板设计白皮书》§1.2「视图裁剪原则」。
    """
    agents_map = _merged_state().get("agents", {})
    agent_names = _load_agent_names()
    agent_list: List[Dict[str, Any]] = []
    online = offline = overload = 0
    for agent_id, a in agents_map.items():
        is_online = bool(a.get("online"))
        cpu = a.get("cpu_percent")
        try:
            cpu_f = float(cpu) if cpu not in (None, "") else None
        except (TypeError, ValueError):
            cpu_f = None
        status = "offline"
        if is_online:
            status = "overload" if (cpu_f is not None and cpu_f > 80) else "online"
        if status == "online":
            online += 1
        elif status == "overload":
            overload += 1
        else:
            offline += 1
        agent_list.append({
            "agent_id": agent_id,
            "name": a.get("display_name") or a.get("name") or agent_id,
            "name_zh": agent_names.get(agent_id, ""),
            "agent_type": a.get("agent_type") or "functional",
            "status": status,
            "online": is_online,
            "cpu_percent": cpu_f,
            "last_heartbeat": a.get("last_heartbeat"),
        })

    alerts = _health_alerts(50) or []
    events = _list_events(30)

    total = len(agent_list)
    if total == 0 or (online + overload) == 0:
        system_status = "down"
    elif overload > 0 or len(alerts) > 0:
        system_status = "degraded"
    else:
        system_status = "normal"

    return {
        "role": "governor",
        "system_status": system_status,
        "agents": {
            "total": total,
            "online": online,
            "offline": offline,
            "overload": overload,
            "list": agent_list,
        },
        "alerts": alerts,
        "events": events,
        "hub_nodes": [
            {"name": "Leader", "status": "online"},
            {"name": "worker-01", "status": "online"},
            {"name": "worker-02", "status": system_status},
            {"name": "witness-01", "status": "online"},
        ],
        "legislation": [
            {"name": "宪法", "status": "done", "progress": 100},
            {"name": "调度法", "status": "done", "progress": 100},
            {"name": "触发法", "status": "draft", "progress": 75},
            {"name": "熔断法", "status": "pending", "progress": 30},
        ],
    }


@app.get("/api/workorders")
async def list_workorders(status: str = "", project_id: str = ""):
    """
    工单导航数据：task_queue 中人工工单（WO- 前缀 + 全部任务）按状态分组。
    返回 {counts: {...}, groups: {pending:[], running:[], done:[], failed:[], draft:[], deploy_wait:[]}}
    """
    db = _workorder_db()
    try:
        where = ["task_id LIKE 'WO-%'"]
        params: List[Any] = []
        if status:
            # 过滤前先映射前端状态到多态(可选，这里保持 1:1)
            where.append("status = ?")
            params.append(status)
        if project_id:
            where.append("payload LIKE ?")
            params.append(f"%{project_id}%")

        sql = f"SELECT * FROM task_queue WHERE {' AND '.join(where)} ORDER BY COALESCE(started_at, '') DESC"
        rows = db.fetchall(sql, tuple(params))
    except Exception as e:
        return {"counts": {}, "groups": {}, "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()

    buckets = ["draft", "pending", "deploy_wait", "running", "done", "failed", "cancelled"]
    groups: Dict[str, List[Dict[str, Any]]] = {k: [] for k in buckets}
    counts: Dict[str, int] = {k: 0 for k in buckets}
    seen_ids = set()

    for r in rows:
        wid = (r.get("task_id") or "").strip()
        if not wid.startswith("WO-"):
            continue
        st = r.get("status") or "pending"
        if st not in groups:
            st = "pending"
        # 工单去重：同一 wo_id 可能因重跑产生重复，取最新一条
        if wid in seen_ids:
            continue
        seen_ids.add(wid)
        item = {
            "work_order_id": wid,
            "project_id": _extract_project_id(r),
            "workflow_id": r.get("workflow_id") or "",
            "display_cap": r.get("display_cap") or "",
            "priority": r.get("priority") or "normal",
            "deadline": r.get("deadline"),
            "sla_seconds": r.get("sla_seconds"),
            "status": st,
            "result_summary": r.get("error_log") or "",
            "output_file_ids": _parse_ids(r.get("output_file_ids")),
            "dispatched_task_id": wid,
            "payload_json": r.get("payload") or "",
            "raw_payload": r.get("raw_payload") or "",
            "created_at": r.get("started_at") or r.get("created_at"),
            "finished_at": r.get("finished_at"),
        }
        groups[st].append(item)
        counts[st] += 1

    return {"counts": counts, "groups": groups}


def _parse_ids(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _extract_project_id(row: Dict[str, Any]) -> str:
    """从工单 payload(JSON) 或 raw_payload(YAML 文本) 中提取 project_id。"""
    raw = row.get("payload") or ""
    if raw:
        try:
            v = json.loads(raw)
            if isinstance(v, dict):
                pid = v.get("project_id") or v.get("project_tag") or ""
                if pid:
                    return str(pid)
        except Exception:
            pass
    raw_text = row.get("raw_payload") or ""
    for line in str(raw_text).splitlines():
        stripped = line.strip()
        if stripped.startswith("project_id"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


@app.post("/api/workorders")
async def create_workorder(payload: Dict[str, Any]):
    """
    人工录入工单（写入 task_queue 单表）。

    请求体：
      {
        "workflow_id": "AKO_quote_agent",
        "display_cap": "💰 报价",
        "project_id": "PRJ-2026-001",
        "payload": {...业务参数对象...},
        "raw_payload": "project_id: ...",   # 原始 YAML，可选
        "priority": "normal",
        "deadline": "...",
        "sla_seconds": 15,
        "save_as": "draft" | "submit"     # draft=存草稿；submit=提交(入队待派发)
      }
    """
    workflow_id = str(payload.get("workflow_id", "")).strip()
    if not workflow_id:
        return {"status": "error", "message": "缺少 workflow_id"}

    save_as = payload.get("save_as", "draft")
    status = "draft" if save_as == "draft" else "pending"

    wo_id = str(payload.get("work_order_id", "")).strip() or _generate_wo_id()

    biz = payload.get("payload") or {}
    if isinstance(biz, dict):
        if payload.get("project_id") and not biz.get("project_id"):
            biz["project_id"] = payload.get("project_id")
    payload_json = json.dumps(biz, ensure_ascii=False) if biz else (
        str(payload.get("raw_payload", ""))
    )

    try:
        db = _workorder_db()
        try:
            db.execute(
                """INSERT INTO task_queue
                   (task_id, workflow_id, trigger_agent, trigger_type, payload, status,
                    display_cap, priority, deadline, sla_seconds, submitter, raw_payload,
                    started_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (wo_id, workflow_id, "operator", "manual", payload_json, status,
                 str(payload.get("display_cap", "")), str(payload.get("priority", "normal")),
                 payload.get("deadline"), payload.get("sla_seconds"),
                 str(payload.get("submitter", "human")),
                 str(payload.get("raw_payload", "")), datetime.now().isoformat()),
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}

    return {
        "status": "ok",
        "work_order_id": wo_id,
        "record_status": status,
        "message": "已存草稿" if save_as == "draft" else "已提交，待派发",
    }


@app.get("/api/workorders/{wo_id}")
async def workorder_detail(wo_id: str):
    """工单详情。"""
    db = _workorder_db()
    try:
        row = db.fetchone("SELECT * FROM task_queue WHERE task_id=?", (wo_id,))
    finally:
        db.close()

    if not row:
        return {"status": "error", "message": f"未找到工单: {wo_id}"}

    return {
        "work_order_id": wo_id,
        "workflow_id": row.get("workflow_id"),
        "display_cap": row.get("display_cap"),
        "project_id": _extract_project_id(row),
        "priority": row.get("priority"),
        "deadline": row.get("deadline"),
        "sla_seconds": row.get("sla_seconds"),
        "status": row.get("status"),
        "payload_json": row.get("payload"),
        "raw_payload": row.get("raw_payload"),
        "result_summary": row.get("error_log"),
        "output_file_ids": _parse_ids(row.get("output_file_ids")),
        "created_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


@app.patch("/api/workorders/{wo_id}")
async def update_workorder(wo_id: str, payload: Dict[str, Any]):
    """
    编辑工单（草稿/未派发可改），或取消。
    body: {\"status\": \"draft|pending|cancelled\", \"payload\": {...}, ...}
    """
    allowed_status = {"draft", "pending", "cancelled"}
    db = _workorder_db()
    try:
        row = db.fetchone("SELECT * FROM task_queue WHERE task_id=?", (wo_id,))
        if not row:
            return {"status": "error", "message": f"未找到工单: {wo_id}"}

        cur_status = row.get("status")
        if cur_status in ("running", "done", "failed"):
            return {"status": "error", "message": f"当前状态 {cur_status} 不允许编辑"}

        new_status = payload.get("status") or cur_status
        if new_status not in allowed_status:
            return {"status": "error", "message": f"非法状态: {new_status}"}

        biz = payload.get("payload")
        payload_json = json.dumps(biz, ensure_ascii=False) if biz is not None else None
        raw = payload.get("raw_payload")

        sets = ["status = ?"]
        params: List[Any] = [new_status]
        if payload_json is not None:
            sets.append("payload = ?")
            params.append(payload_json)
        if raw is not None:
            sets.append("raw_payload = ?")
            params.append(str(raw))
        if "priority" in payload:
            sets.append("priority = ?")
            params.append(str(payload.get("priority")))
        if "deadline" in payload:
            sets.append("deadline = ?")
            params.append(payload.get("deadline"))
        params.append(wo_id)

        db.execute(f"UPDATE task_queue SET {', '.join(sets)} WHERE task_id = ?", tuple(params))
        db.commit()
    finally:
        db.close()

    return {"status": "ok", "work_order_id": wo_id, "record_status": new_status}


@app.post("/api/workorders/{wo_id}/dispatch")
async def dispatch_workorder(wo_id: str):
    """
    派发工单给 Agent：

    1. 未部署（source_dir 不存在）→ 标 deploy_wait（"待部署"），不调 Agent。
    2. 已部署 → 以 wo_id 作为 task_id 调 hub_api.submit_task（单项业务 payload 透传）。
       结果经 master/nodes.py 的 UPSERT 原地回写该行 status。
    """
    db = _workorder_db()
    try:
        row = db.fetchone("SELECT * FROM task_queue WHERE task_id=?", (wo_id,))
    finally:
        db.close()

    if not row:
        return {"status": "error", "message": f"未找到工单: {wo_id}"}

    workflow_id = row.get("workflow_id") or ""
    if not workflow_id:
        return {"status": "error", "message": "工单缺 workflow_id，无法派发"}

    # 未部署检查
    if not _spoke_deployable(workflow_id):
        db = _workorder_db()
        try:
            db.execute(
                "UPDATE task_queue SET status='deploy_wait' WHERE task_id=?",
                (wo_id,),
            )
            db.commit()
        finally:
            db.close()
        return {
            "status": "ok",
            "work_order_id": wo_id,
            "record_status": "deploy_wait",
            "message": f"目标 Agent {workflow_id} 尚未部署，已标记为待部署",
        }

    # 解析业务 payload
    biz: Dict[str, Any] = {}
    raw = row.get("payload") or ""
    if raw:
        try:
            biz = json.loads(raw) if str(raw).strip().startswith("{") else {"intent": str(raw)}
        except Exception:
            biz = {"intent": str(raw)}

    biz["workflow_id"] = workflow_id
    if row.get("display_cap"):
        biz.setdefault("display_cap", row.get("display_cap"))

    # 异步后台执行：立即返回 running，由 /api/workorders/{id}/result 轮询真实状态。
    # 同步执行会阻塞 HTTP 响应（LLM/重型 Agent 可达分钟级），导致员工台"无响应"。
    import threading

    def _run() -> None:
        from hub_api import submit_task
        try:
            submit_task(biz, task_id=wo_id, trigger="operator")
        except Exception as exc:  # noqa: BLE001
            db2 = _workorder_db()
            try:
                db2.execute(
                    "UPDATE task_queue SET status='failed', error_log=? WHERE task_id=?",
                    (f"{type(exc).__name__}: {exc}", wo_id),
                )
                db2.commit()
            finally:
                db2.close()

    threading.Thread(target=_run, daemon=True, name=f"wo-{wo_id}").start()

    return {
        "status": "ok",
        "work_order_id": wo_id,
        "record_status": "running",
        "message": "已派发，后台执行中（轮询 /result 获取真实状态）",
    }


@app.get("/api/workorders/{wo_id}/result")
async def workorder_result(wo_id: str):
    """轮询工单结果（聚合最新 task_queue 行 + 输出文件）。"""
    db = _workorder_db()
    try:
        row = db.fetchone("SELECT * FROM task_queue WHERE task_id=?", (wo_id,))
    finally:
        db.close()

    if not row:
        return {"status": "error", "message": f"未找到工单: {wo_id}"}

    return {
        "work_order_id": wo_id,
        "status": row.get("status"),
        "result_summary": row.get("error_log"),
        "output_file_ids": _parse_ids(row.get("output_file_ids")),
        "finished_at": row.get("finished_at"),
    }


@app.get("/api/files/{file_id}/download")
async def file_download(file_id: str):
    """下载文件注册表中的产出文件。"""
    from hub_api import _resolve_paths as hub_resolve

    try:
        paths = hub_resolve()
    except Exception:
        paths = _resolve_paths()

    from core.hub_db import HubDB

    db = HubDB(paths["db_path"])
    try:
        db.connect()
        db.init_schema()
        row = db.fetchone("SELECT * FROM file_registry WHERE file_id=?", (file_id,))
    finally:
        db.close()

    if not row:
        return {"status": "error", "message": f"未找到文件: {file_id}"}

    abs_path = row.get("abs_path") or ""
    p = Path(abs_path)
    if not p.exists():
        return {"status": "error", "message": f"文件不存在: {abs_path}"}

    return FileResponse(str(p), filename=p.name)


# ── WebSocket ────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── 文件监听 + 广播 ─────────────────────────────────────────────

def get_state_mtime() -> float:
    return STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0


async def watch_and_broadcast():
    last_mtime = get_state_mtime()
    while True:
        await asyncio.sleep(1)
        current_mtime = get_state_mtime()
        if current_mtime != last_mtime:
            last_mtime = current_mtime
            await manager.broadcast({
                "type": "state_update",
                "data": _merged_state(),
                "timestamp": datetime.utcnow().isoformat(),
            })


@app.on_event("startup")
async def startup_event():
    _ensure_state_file()
    _init_heartbeat_db()
    asyncio.create_task(watch_and_broadcast())
    asyncio.create_task(_hub_self_heartbeat_loop())


async def _hub_self_heartbeat_loop() -> None:
    """hub 自心跳（治理概览中 AKO_hub 自身在线状态的诚实来源）。

    看板运行于 hub 进程内，hub 之前无人替它上报心跳 → 概览恒 offline。
    每 30s POST :5000/heartbeat（与各 spoke 相同通道）。
    """
    import httpx
    while True:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post("http://127.0.0.1:5000/heartbeat", json={
                    "agent_id": "AKO_hub",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "alive",
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                })
        except Exception:
            pass
        await asyncio.sleep(30)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)