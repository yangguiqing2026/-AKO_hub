"""
AKO Dashboard — 治理指挥室服务端鉴权测试

验证 2026-09-03 治理数据服务端会话鉴权：
  1. /api/governance/* 未携带有效治理会话 → 401（修复：此前裸 HTTP，仅前端 localStorage 遮罩）。
  2. governor 指纹登录成功签发会话 token；携带 token 可读治理数据。
  3. 会话过期/伪造 → 401。
  4. identity 服务不可达 → 登录返回明确文案（不再误导为"指纹不匹配"）。
  5. 治理页面 HTML 壳公开可开（敏感数据在 API 层受保护）——固化设计意图。

用法：
    python -m pytest tests/test_dashboard_governance_auth.py -v
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

import dashboard.app as app_mod


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    """隔离文件副作用：状态文件/心跳库指向 tmp；启动钩子的后台任务替换为 no-op，
    避免向真实 :5000 心跳库写入测试期心跳（review #14）。"""
    monkeypatch.setattr(app_mod, "STATE_FILE", tmp_path / "pipeline_state.json")
    monkeypatch.setattr(app_mod, "HEARTBEAT_DB", tmp_path / "ako_hub.db")

    async def _noop() -> None:
        return None

    monkeypatch.setattr(app_mod, "_hub_self_heartbeat_loop", _noop)
    monkeypatch.setattr(app_mod, "watch_and_broadcast", _noop)
    app_mod._GOV_SESSIONS.clear()
    app_mod._login_attempts.clear()
    app_mod._allowlist_cache.update({"at": 0.0, "ids": set()})
    with TestClient(app_mod.app) as c:
        yield c
    app_mod._GOV_SESSIONS.clear()
    app_mod._login_attempts.clear()


# ── 工具 ─────────────────────────────────────────────────────────

def _stub_verify(result: app_mod.VerifyResult) -> Callable[[str], Any]:
    """身份层替身：返回固定 (state, human)，供 monkeypatch 使用。"""
    async def _verify(fp: str) -> app_mod.VerifyResult:
        return result
    return _verify


def _login_as_governor(client: TestClient, monkeypatch) -> str:
    """monkeypatch 身份层返回 ok，走通双层校验，返回服务端 token。"""
    monkeypatch.setattr(
        app_mod,
        "_verify_human_via_identity_service",
        _stub_verify(("ok", {"human_id": "HUM-YANGGUIQING-001", "name": "杨贵清", "role": "安全官_L3"})),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body.get("token"), f"登录应签发会话 token，实际: {body}"
    return body["token"]


def _gov_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 1. 未鉴权 / 伪造 token → 401 ─────────────────────────────────
# 2026-09-03 全面上锁（index.html 匿名总控台退役）：治理 + 运维只读/写接口全部要求会话

LOCKED_GETS = [
    "/api/governance/overview", "/api/governance/topology",
    "/api/state", "/api/agents",
    "/api/health/agents", "/api/health/alerts",
    "/api/spokes", "/api/http-agents", "/api/events",
    "/api/knowledge-bases", "/api/files", "/api/tasks",
    "/api/files/nonexistent/download",
]


def test_all_locked_apis_require_session(client: TestClient):
    for path in LOCKED_GETS:
        r = client.get(path)
        assert r.status_code == 401, f"{path} 未鉴权应 401，实际 {r.status_code}: {r.text[:120]}"
    # 写接口同样被会话门禁挡住（依赖在 body 校验前执行）
    assert client.post("/api/tasks", json={}).status_code == 401
    assert client.post("/api/spokes", json={}).status_code == 401
    assert client.delete("/api/spokes/whatever").status_code == 401


def test_governance_api_rejects_forged_token(client: TestClient):
    headers = _gov_headers("forged-token-not-in-sessions")
    for path in LOCKED_GETS:
        r = client.get(path, headers=headers)
        assert r.status_code == 401, f"{path} 伪造 token 应 401，实际 {r.status_code}"


def test_token_reads_previously_public_apis(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    h = _gov_headers(token)
    for path in ("/api/state", "/api/agents", "/api/health/alerts", "/api/events", "/api/spokes"):
        r = client.get(path, headers=h)
        assert r.status_code == 200, f"{path} 带治理会话应 200，实际 {r.status_code}"


def test_old_anonymous_console_page_retired(client: TestClient, monkeypatch):
    # index.html（旧匿名总控台）已退役：静态挂载 404；首页落 landing/治理页
    assert client.get("/static/index.html").status_code == 404
    assert client.get("/").status_code == 200
    token = _login_as_governor(client, monkeypatch)
    # WS 同样受治理会话保护：无 token 拒绝升级（1008）
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/ws"):
            raise AssertionError("无 token 的 /ws 不应允许连接")
    except WebSocketDisconnect as e:
        assert e.code == 1008
    with client.websocket_connect(f"/ws?token={token}"):
        pass  # 带 token 升级成功


def test_governance_api_rejects_expired_session(client: TestClient):
    app_mod._GOV_SESSIONS["expired-token"] = {
        "human_id": "HUM-YANGGUIQING-001", "name": "杨贵清", "role": "governor",
        "expires_at": time.time() - 1,
    }
    r = client.get("/api/governance/overview", headers=_gov_headers("expired-token"))
    assert r.status_code == 401
    # 过期条目应从会话表清理
    assert "expired-token" not in app_mod._GOV_SESSIONS


# ── 2. 登录签发 token → 携带可读 ─────────────────────────────────

def test_governor_login_issues_token_and_reads_overview(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    r = client.get("/api/governance/overview", headers=_gov_headers(token))
    assert r.status_code == 200
    body = r.json()
    assert body.get("role") == "governor"
    assert "agents" in body and "system_status" in body
    assert "flow" in body  # 真实工单流转字段（审计面板数据源）


def test_governor_token_reads_topology(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    r = client.get("/api/governance/topology", headers=_gov_headers(token))
    assert r.status_code == 200
    body = r.json()
    assert "rings" in body and "hub" in body and "edges" in body
    assert "flow" in body  # 真实流转动效边（替代静态边动画）


def test_login_format_validation(client: TestClient):
    r = client.post("/api/auth/governor-login", json={"fingerprint": "12345"})
    assert r.json().get("status") == "fail"
    assert "6 位" in r.json().get("message", "")


# ── 3. 身份层状态语义（问题 2：不可达 ≠ 指纹不匹配） ─────────────

def test_login_reports_unreachable_identity_service(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("unreachable", None)),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    body = r.json()
    assert body["status"] == "fail"
    assert "身份服务不可达" in body.get("message", ""), body


def test_login_reports_no_registry(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("no_registry", None)),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    assert "身份注册册" in r.json().get("message", "")


def test_login_reports_fingerprint_rejected(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("rejected", None)),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    body = r.json()
    assert body["status"] == "fail"
    assert "指纹不匹配" in body.get("message", "")


def test_login_requires_allowlist_even_when_identity_ok(client: TestClient, monkeypatch):
    # 身份册验证通过但不在 governor allowlist
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("ok", {"human_id": "HUM-NOT-IN-LIST-001", "name": "未授权人", "role": "员工"})),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    body = r.json()
    assert body["status"] == "fail"
    assert "无治理指挥室权限" in body.get("message", "")


# ── 4. 页面壳公开、数据受保护（设计意图固化） ────────────────────

def test_governor_pages_open_anonymously_but_api_protected(client: TestClient):
    assert client.get("/governor").status_code == 200
    assert client.get("/heatmap").status_code == 200
    assert client.get("/api/governance/topology").status_code == 401


# ── review 修复回归：登录语义 / 限流 / 会话回收 ───────────────────

def test_login_reports_no_active(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("no_active", None)),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    body = r.json()
    assert body["status"] == "fail"
    assert "无 active" in body.get("message", "")


def test_login_allowlist_miss_does_not_echo_name(client: TestClient, monkeypatch):
    # 不允许把"注册册命中但未授权"当身份 oracle 回显真名
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("ok", {"human_id": "HUM-NOT-IN-LIST-001", "name": "不应泄漏者", "role": "员工"})),
    )
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    body = r.json()
    assert body["status"] == "fail"
    assert "不应泄漏者" not in body.get("message", "")


def test_login_throttled_after_max_attempts(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        app_mod, "_verify_human_via_identity_service",
        _stub_verify(("rejected", None)),
    )
    for _ in range(app_mod._LOGIN_MAX_ATTEMPTS):
        r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
        assert "过于频繁" not in r.json().get("message", "")
    r = client.post("/api/auth/governor-login", json={"fingerprint": "123456"})
    assert "过于频繁" in r.json().get("message", "")


def test_allowlist_removal_revokes_live_session(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    assert client.get("/api/governance/overview", headers=_gov_headers(token)).status_code == 200
    # 治理者从 allowlist 移除 → 会话即时回收（不依赖 TTL/重启）
    monkeypatch.setattr(app_mod, "_load_governor_access", lambda: [])
    app_mod._allowlist_cache.update({"at": 0.0, "ids": set()})
    assert client.get("/api/governance/overview", headers=_gov_headers(token)).status_code == 401


def test_relogin_revokes_previous_token(client: TestClient, monkeypatch):
    t1 = _login_as_governor(client, monkeypatch)
    t2 = _login_as_governor(client, monkeypatch)
    assert t1 != t2
    assert client.get("/api/governance/overview", headers=_gov_headers(t1)).status_code == 401
    assert client.get("/api/governance/overview", headers=_gov_headers(t2)).status_code == 200


def test_logout_revokes_session(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    r = client.post("/api/auth/governor-logout", headers=_gov_headers(token))
    assert r.json().get("status") == "ok"
    assert client.get("/api/governance/overview", headers=_gov_headers(token)).status_code == 401


def test_issue_gov_session_sweeps_expired():
    app_mod._GOV_SESSIONS.clear()
    app_mod._GOV_SESSIONS["stale-1"] = {"human_id": "HUM-X", "name": "x", "role": "governor",
                                        "expires_at": time.time() - 10}
    app_mod._issue_gov_session("HUM-NEW-001", "新")
    assert "stale-1" not in app_mod._GOV_SESSIONS
    app_mod._GOV_SESSIONS.clear()


# ── review 修复回归：_verify 状态判定（HTTP 状态 / 应答形态 / 候选状态） ──

class _FakeResp:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _FakeHttpClient:
    """替代 httpx.AsyncClient：每次 post 调 responder()（可抛异常模拟网络失败）。"""

    def __init__(self, responder: Callable[[], Any]):
        self._responder = responder

    async def __aenter__(self) -> "_FakeHttpClient":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        return self._responder()


def _run_verify(monkeypatch: Any, tmp_path: Path,
                responder: Callable[[], Any], statuses: list) -> Any:
    reg = tmp_path / "human_identities.yaml"
    lines = ["human_identities:"]
    for i, st in enumerate(statuses):
        lines += [f"- human_id: HUM-T{i}-001", f"  name: T{i}", f"  status: {st}"]
    reg.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(app_mod, "_IDENTITY_REG_FILE", reg)
    import httpx as httpx_mod
    monkeypatch.setattr(httpx_mod, "AsyncClient", lambda **kw: _FakeHttpClient(responder))
    return asyncio.run(app_mod._verify_human_via_identity_service("123456"))


def test_verify_http_500_is_unreachable(monkeypatch: Any, tmp_path: Path):
    state, human = _run_verify(monkeypatch, tmp_path,
                               lambda: _FakeResp(500, {"detail": "boom"}), ["active"])
    assert state == "unreachable" and human is None


def test_verify_non_dict_200_is_unreachable(monkeypatch: Any, tmp_path: Path):
    state, _ = _run_verify(monkeypatch, tmp_path, lambda: _FakeResp(200, ["not-a-dict"]), ["active"])
    assert state == "unreachable"


def test_verify_rejected_on_verified_false(monkeypatch: Any, tmp_path: Path):
    state, _ = _run_verify(monkeypatch, tmp_path,
                           lambda: _FakeResp(200, {"verified": False}), ["active"])
    assert state == "rejected"


def test_verify_no_active_candidates(monkeypatch: Any, tmp_path: Path):
    state, _ = _run_verify(monkeypatch, tmp_path,
                           lambda: _FakeResp(200, {"verified": True}), ["inactive"])
    assert state == "no_active"


def test_verify_network_error_is_unreachable(monkeypatch: Any, tmp_path: Path):
    def _boom() -> Any:
        raise ConnectionError("refused")
    state, _ = _run_verify(monkeypatch, tmp_path, _boom, ["active"])
    assert state == "unreachable"


def test_verify_ok_on_verified_true(monkeypatch: Any, tmp_path: Path):
    state, human = _run_verify(monkeypatch, tmp_path,
                               lambda: _FakeResp(200, {"verified": True}), ["active"])
    assert state == "ok" and human and human["human_id"] == "HUM-T0-001"


# ── review 修复回归：topology 双名归一（心跳键无 _agent 后缀也判在线） ──

def test_topology_matches_suffixless_heartbeat_keys(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    # 注册键带 _agent 后缀，心跳键无后缀（AKO_knowledge / AKO_identity_service）
    monkeypatch.setattr(
        app_mod, "_registry_agents",
        lambda: [{"agent_id": "AKO_knowledge_agent", "domain": "基座域"},
                 {"agent_id": "AKO_hub_agent", "domain": ""}],
    )
    monkeypatch.setattr(
        app_mod, "_heartbeat_status_map",
        lambda: {"AKO_knowledge": {"online": True}, "AKO_hub": {"online": True}},
    )
    monkeypatch.setattr(app_mod, "_load_agent_names", lambda: {})
    monkeypatch.setattr(app_mod, "_topology_edges", lambda: [])
    r = client.get("/api/governance/topology", headers=_gov_headers(token))
    body = r.json()
    assert body["online_total"] == 2, body  # 双名归一后两实体都应在线
    hub = body["hub"]
    assert hub and hub["online"] is True


def test_worker02_node_status_maps_normal_to_online(client: TestClient, monkeypatch):
    token = _login_as_governor(client, monkeypatch)
    monkeypatch.setattr(app_mod, "_merged_state", lambda: {"agents": {}})
    monkeypatch.setattr(app_mod, "_health_alerts", lambda limit=50, only_open=False: [])
    monkeypatch.setattr(app_mod, "_list_events", lambda limit=30: {})
    r = client.get("/api/governance/overview", headers=_gov_headers(token))
    body = r.json()
    assert body["system_status"] == "down"  # 空 agent 集 → down
    nodes = {n["name"]: n["status"] for n in body["hub_nodes"]}
    assert nodes["worker-02"] == "down"


def test_topology_prefers_live_alias_row_over_stale_canonical(client: TestClient, monkeypatch):
    # 双行并存：别名行(带心跳, 字母序靠前) + 规范行(无心跳) → 应取在线方（overview/topology 一致）
    token = _login_as_governor(client, monkeypatch)
    monkeypatch.setattr(
        app_mod, "_registry_agents",
        lambda: [{"agent_id": "AKO_identity_service_agent", "domain": "基座域"}],
    )
    monkeypatch.setattr(
        app_mod, "_heartbeat_status_map",
        lambda: {
            "AKO_identity_service": {"online": True, "last_heartbeat": "t"},
            "AKO_identity_service_agent": {"online": False},
        },
    )
    monkeypatch.setattr(app_mod, "_load_agent_names", lambda: {})
    monkeypatch.setattr(app_mod, "_topology_edges", lambda: [])
    r = client.get("/api/governance/topology", headers=_gov_headers(token))
    body = r.json()
    assert body["online_total"] == 1, body
