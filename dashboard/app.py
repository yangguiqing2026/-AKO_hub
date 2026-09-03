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
from typing import Any, Dict, List, Literal, Optional, Tuple

import uuid
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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

# 身份注册册副本（唯一法源 AKO_identity_service 的本地镜像，登录遍历对象）
_IDENTITY_REG_FILE = Path(r"D:\AKO\AKO_identity_service\config\human_identities.yaml")
# 治理登录限流：6 位指纹空间小，须服务端限速。15 分钟窗口内同 IP 最多 30 次尝试。
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_ATTEMPTS = 30
_login_attempts: Dict[str, List[float]] = {}   # ip -> [尝试时间戳, ...]

def _login_throttle(request: Request) -> Optional[str]:
    """同 IP governor-login 尝试限流；未超限返回 None 并记账。"""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
    if len(hits) >= _LOGIN_MAX_ATTEMPTS:
        _login_attempts[ip] = hits
        return f"尝试过于频繁，请 {_LOGIN_WINDOW_SECONDS // 60} 分钟后再试"
    hits.append(now)
    _login_attempts[ip] = hits
    return None

VerifyState = Literal["ok", "rejected", "no_active", "unreachable", "no_registry"]
VerifyResult = Tuple[VerifyState, Optional[Dict[str, str]]]

async def _verify_human_via_identity_service(fp: str) -> VerifyResult:
    """经身份认证层逐人校验指纹（人类身份注册册为唯一法源）。

    从本地注册册副本读取 human_id 列表，逐个 POST /api/v1/identity/verify。
    返回 (state, human)：
      ok          指纹命中且 /verify verified=True
      rejected    服务正常应答但无人通过（指纹错误）
      no_active   注册册无 active 候选（无人可验，身份册状态问题，非服务故障）
      unreachable 有候选但服务异常/不可达（网络失败、非 2xx、或应答非 dict）
      no_registry 注册册文件缺失或不可读
    """
    import httpx
    if not _IDENTITY_REG_FILE.exists():
        return ("no_registry", None)
    try:
        import yaml
        humans = (yaml.safe_load(_IDENTITY_REG_FILE.read_text(encoding="utf-8-sig")) or {}).get("human_identities", []) or []
    except Exception:
        return ("no_registry", None)
    attempted = False
    reached = False
    for h in humans:
        if h.get("status") != "active":
            continue
        attempted = True
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
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        reached = True
        if data.get("verified") is True:
            return ("ok", {"human_id": h.get("human_id", ""), "name": h.get("name", ""),
                           "role": h.get("role", "")})
    if not attempted:
        return ("no_active", None)
    return ("unreachable", None) if not reached else ("rejected", None)

# ── 治理会话（服务端鉴权层：token 签发 / 校验） ────────────────────
# 2026-09-03 新增：/api/governance/* 此前裸 HTTP 仅靠前端 localStorage 遮罩，
# curl 即可直取治理数据；现改为登录签发 12h 会话 token，数据接口强制校验。

_GOV_SESSIONS: Dict[str, Dict[str, Any]] = {}   # token -> {human_id, name, role, expires_at}
_GOV_TTL_SECONDS = 12 * 3600
_GOV_ALLOWLIST_CACHE_TTL = 30.0
_allowlist_cache: Dict[str, Any] = {"at": 0.0, "ids": set()}

def _governor_allowed_ids() -> set:
    """治理白名单 human_id 集合（30s 缓存；改 allowlist 后 ≤30s 内回收生效）。"""
    now = time.time()
    if now - _allowlist_cache["at"] > _GOV_ALLOWLIST_CACHE_TTL:
        _allowlist_cache["at"] = now
        _allowlist_cache["ids"] = {g.get("human_id", "") for g in _load_governor_access()}
    return _allowlist_cache["ids"]

def _expire_gov_sessions() -> None:
    """清理已过期会话（进程内存态；重启后全部失效，前端 401 后重新指纹登录）。"""
    now = time.time()
    for t in [t for t, s in _GOV_SESSIONS.items() if s["expires_at"] <= now]:
        _GOV_SESSIONS.pop(t, None)

def _revoke_gov_sessions(human_id: str) -> None:
    """撤销指定治理者的全部会话（重登顶替 / 权限回收用）。"""
    for t in [t for t, s in _GOV_SESSIONS.items() if s["human_id"] == human_id]:
        _GOV_SESSIONS.pop(t, None)

def _issue_gov_session(human_id: str, name: str) -> str:
    """为治理者签发会话 token；同人旧会话全部失效，过期条目顺手清理。"""
    _expire_gov_sessions()
    _revoke_gov_sessions(human_id)
    token = secrets.token_urlsafe(24)
    _GOV_SESSIONS[token] = {
        "human_id": human_id,
        "name": name,
        "role": "governor",
        "expires_at": time.time() + _GOV_TTL_SECONDS,
    }
    return token

def _gov_token_ok(token: str) -> bool:
    """治理会话有效性（存在 + 未过期 + 白名单仍在册）；无效即清理。"""
    sess = _GOV_SESSIONS.get(token) if token else None
    if not sess or sess["expires_at"] <= time.time():
        _GOV_SESSIONS.pop(token, None)
        return False
    if sess["human_id"] not in _governor_allowed_ids():
        _GOV_SESSIONS.pop(token, None)
        return False
    return True

def _require_governor(request: Request) -> Dict[str, Any]:
    """FastAPI 依赖：治理数据接口必须携带有效治理会话。

    取 Authorization: Bearer <token>（兼容 X-Gov-Token 头）；
    缺失 / 伪造 / 过期 / 白名单已移除 一律 401（白名单移除即回收，不必等 TTL）。
    """
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        token = (request.headers.get("x-gov-token") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="治理会话缺失，请先指纹登录")
    if not _gov_token_ok(token):
        raise HTTPException(status_code=401, detail="治理会话无效、已过期或权限已回收，请重新登录")
    return _GOV_SESSIONS[token]

def _load_governor_access() -> List[Dict[str, str]]:
    """读取治理指挥室访问控制表（human_id 白名单，无凭证存储）。

    表中 role 字段为身份册角色元信息（展示用）；登录态 role 由服务端固定为 governor。
    """
    if GOVERNOR_ACCESS_FILE.exists():
        try:
            import yaml
            with open(GOVERNOR_ACCESS_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("governors", []) or []
        except Exception:
            pass
    return []

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
    governor_file = STATIC_DIR / "governor.html"
    if governor_file.exists():
        return governor_file.read_text(encoding="utf-8")
    return "<h1>AKO Dashboard</h1><p>治理指挥室页面缺失。</p>"

@app.get("/api/state")
async def get_state(_gov: Dict[str, Any] = Depends(_require_governor)):
    return _merged_state()

@app.get("/api/agents")
async def get_agents(_gov: Dict[str, Any] = Depends(_require_governor)):
    return _merged_state().get("agents", {})

# ── 健康巡检路由 ─────────────────────────────────────────────────

@app.get("/api/health/agents")
async def health_agents(_gov: Dict[str, Any] = Depends(_require_governor)):
    return _health_agents()

@app.get("/api/health/alerts")
async def health_alerts(_gov: Dict[str, Any] = Depends(_require_governor)):
    return {"alerts": _health_alerts()}

# ── Agent 注册中心路由 ───────────────────────────────────────────

@app.get("/api/spokes")
async def get_spokes(spoke_type: str = "", _gov: Dict[str, Any] = Depends(_require_governor)):
    return {"spokes": _list_spokes(spoke_type)}

@app.post("/api/spokes")
async def create_spoke(payload: Dict[str, Any], _gov: Dict[str, Any] = Depends(_require_governor)):
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
async def delete_spoke(workflow_id: str, _gov: Dict[str, Any] = Depends(_require_governor)):
    """移除一个已注册的 Spoke。"""
    from hub_api import remove_spoke
    return remove_spoke(workflow_id)

@app.get("/api/http-agents")
async def http_agents(_gov: Dict[str, Any] = Depends(_require_governor)):
    """返回 HTTP 注册中心登记的 Agent（含完整 agent_card）。"""
    return _http_registered_agents()

# ── 事件流路由 ───────────────────────────────────────────────────

@app.get("/api/events")
async def get_events(limit: int = 100, _gov: Dict[str, Any] = Depends(_require_governor)):
    return _list_events(limit)

# ── 知识库与文件路由 ─────────────────────────────────────────────

@app.get("/api/knowledge-bases")
async def knowledge_bases(_gov: Dict[str, Any] = Depends(_require_governor)):
    """列出知识库。"""
    try:
        from hub_api import list_knowledge_bases
        return {"knowledge_bases": list_knowledge_bases()}
    except Exception as e:
        return {"knowledge_bases": [], "error": f"{type(e).__name__}: {e}"}

@app.get("/api/files")
async def get_files(project_tag: str = "", limit: int = 50, _gov: Dict[str, Any] = Depends(_require_governor)):
    """浏览已注册文件。"""
    from hub_api import list_files
    return list_files(project_tag=project_tag, limit=limit)

# ── 任务路由（Hub 唯一 Web 任务入口） ─────────────────────────────

@app.post("/api/tasks")
def create_task(payload: Dict[str, Any], _gov: Dict[str, Any] = Depends(_require_governor)):
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
def list_tasks(_gov: Dict[str, Any] = Depends(_require_governor)):
    """返回任务队列（最近 100 条）。"""
    return _list_tasks()

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
async def governor_login(payload: Dict[str, Any], request: Request):
    """
    治理者指纹登录校验（role=governor，治理指挥室入口）。

    认证链路（2026-08-27 全面切换身份认证层；2026-09-03 增会话签发与限流）：
    1. AKO_identity_service /verify 逐人校验（身份注册册唯一法源）
    2. 命中者须在治理指挥室 allowlist（config/governor_access.yaml，human_id 白名单）
    3. 通过后签发 12h 会话 token（同人旧会话全部失效）；治理数据 API 凭 token 访问
    4. 同 IP 15 分钟限 30 次尝试（6 位指纹空间小，须限速防爆破）
    """
    fp = str(payload.get("fingerprint", "") or "").strip()
    if not fp.isdigit() or len(fp) != 6:
        return {"status": "fail", "message": "请输入 6 位数字指纹"}

    throttle_msg = _login_throttle(request)
    if throttle_msg:
        return {"status": "fail", "message": throttle_msg}

    state, human = await _verify_human_via_identity_service(fp)
    if state == "unreachable":
        return {"status": "fail",
                "message": "身份服务不可达或异常，请确认 AKO_identity_service(:5025) 在线后重试"}
    if state == "no_registry":
        return {"status": "fail", "message": "身份注册册缺失，请联系体系管理员"}
    if state == "no_active":
        return {"status": "fail", "message": "身份注册册无 active 候选，请联系体系管理员"}
    if state != "ok" or not human:
        return {"status": "fail", "message": "指纹不匹配，无访问权限"}

    for g in _load_governor_access():
        if g.get("human_id") == human.get("human_id"):
            token = _issue_gov_session(human.get("human_id", ""),
                                       g.get("name") or human.get("name", ""))
            return {"status": "ok", "name": g.get("name") or human.get("name", ""),
                    "role": "governor", "human_id": human.get("human_id"),
                    "token": token}
    # 不回显真实姓名：避免把"注册册命中 + 未授权"当作身份 oracle
    return {"status": "fail", "message": "指纹已验证但无治理指挥室权限"}

@app.post("/api/auth/governor-logout")
async def governor_logout(request: Request):
    """治理者退出：失效当前会话 token（幂等，无 token 亦返回 ok）。"""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if token:
        _GOV_SESSIONS.pop(token, None)
    return {"status": "ok"}

@app.get("/landing", response_class=HTMLResponse)
async def landing():
    """落地页（默认入口）。"""
    f = STATIC_DIR / "landing.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<h1>AKO</h1><p>landing.html 尚未构建。</p>"

@app.get("/governor", response_class=HTMLResponse)
async def governor():
    """AKO 治理指挥室页面入口（治理者视图，role=governor；数据经 /api/governance/* 会话鉴权）。"""
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
async def governance_topology(_gov: Dict[str, Any] = Depends(_require_governor)):
    """
    治理指挥室拓扑数据源（治理会话保护，无 token 401）：
    - rings: 三层同心圆（知识层/运维层/工具层），hub 为圆心
    - 每实体含 online/lifecycle_state/quality_tier/domain/layer/color
    - edges: 实际连接 = 心跳边（在线实体→hub）+ agent_edges.yaml 静态边（仅双方已注册）
    """
    registry = _registry_agents()
    hb = _heartbeat_status_map()
    names = _load_agent_names()

    # 归一键首见优先（与 _merged_state 同款）：别名行（AKO_identity_service，带心跳）先于
    # 规范行（AKO_identity_service_agent）出现 → 双行并存时取在线方，topology/overview 计数一致
    hb_norm: Dict[str, Dict[str, Any]] = {}
    for k, v in hb.items():
        hb_norm.setdefault(_norm_agent_key(k), v)

    by_id: Dict[str, Dict[str, Any]] = {}
    for m in registry:
        aid = m.get("agent_id", "")
        if not aid:
            continue
        # 统一双名匹配：注册键（AKO_hub_agent / AKO_knowledge_agent）↔ 心跳键（AKO_hub / AKO_knowledge）
        # 2026-09-03 修复：此前仅 hub 特判，knowledge/identity 等无后缀心跳键实体恒判离线
        hb_status = hb_norm.get(_norm_agent_key(aid)) or hb.get(aid) or {}
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

@app.get("/api/governance/overview")
async def governance_overview(_gov: Dict[str, Any] = Depends(_require_governor)):
    """
    治理指挥室数据聚合（治理会话保护，无 token 401；角色裁剪：role=governor）。

    仅返回治理/监控维度数据（Agent 健康、告警、审计事件、Hub 节点、立法进度），
    不含员工侧操作细节 —— 员工工作台已于 2026-09 迁移至 AKO_hub_intake_agent，
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
            # 2026-09-03 修复：normal 不是节点状态值，前端只认 online/degraded → worker-02 恒误红
            {"name": "worker-02", "status": {"normal": "online", "degraded": "degraded"}.get(system_status, "down")},
            {"name": "witness-01", "status": "online"},
        ],
        "legislation": [
            {"name": "宪法", "status": "done", "progress": 100},
            {"name": "调度法", "status": "done", "progress": 100},
            {"name": "触发法", "status": "draft", "progress": 75},
            {"name": "熔断法", "status": "pending", "progress": 30},
        ],
    }

@app.get("/api/files/{file_id}/download")
async def file_download(file_id: str, _gov: Dict[str, Any] = Depends(_require_governor)):
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
    # 治理会话保护：WS 无法带自定义头，token 走查询参数；无效即关闭(1008 policy violation)
    token = websocket.query_params.get("token", "")
    if not _gov_token_ok(token):
        await websocket.close(code=1008)
        return
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
