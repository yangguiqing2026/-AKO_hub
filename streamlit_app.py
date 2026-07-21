"""
AKO Hub — Streamlit 运维仪表盘 v3.2
11 模块：P0 监控(系统总览/Agent/Workflow/任务队列) + P1 操作(任务提交/知识库/同步/日志) + P2 分析(任务历史/错误追踪/配置面板)

启动: streamlit run streamlit_app.py --server.port 7860 --server.address 127.0.0.1
"""
import json
import sys
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 路径初始化 ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd
import urllib.request

# ── 品牌色常量 ───────────────────────────────────────────────────────
C_BG       = "#FFFFFF"
C_SIDEBAR  = "#231E1C"
C_CARD     = "#F5F5F5"
C_GOLD     = "#B99B5F"
C_AMBER    = "#A08C64"
C_DARK     = "#231E1C"
C_GRAY     = "#C3BEB4"
C_RED      = "#D32F2F"
C_GREEN    = "#388E3C"
C_YELLOW   = "#F9A825"
C_OFFLINE  = "#9E9E9E"
C_WHITE_TX = "#E8E4DF"

# ── 数据库路径 ───────────────────────────────────────────────────────
DB_AGE  = PROJECT_ROOT / "data" / "age_hub.db"
DB_AKO  = PROJECT_ROOT / "data" / "ako_hub.db"

# ── 页面配置 ─────────────────────────────────────────────────────────
st.set_page_config(page_title="AKO Hub 控制面板", page_icon="🏗️", layout="wide")

# ═══════════════════════════════════════════════════════════════════════
# CSS 注入
# ═══════════════════════════════════════════════════════════════════════
st.markdown(f"""
<style>
    .stApp {{ background-color: {C_BG}; }}
    section[data-testid="stSidebar"] {{
        background-color: {C_SIDEBAR};
    }}
    section[data-testid="stSidebar"] * {{
        color: {C_WHITE_TX} !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
        color: {C_GOLD} !important;
    }}

    /* 指标卡片 */
    [data-testid="stMetric"] {{
        background: {C_CARD};
        border-radius: 10px;
        padding: 1rem;
        box-shadow: 0 1px 6px rgba(35,30,28,0.06);
        border-left: 4px solid {C_GOLD};
    }}
    [data-testid="stMetricLabel"] p {{
        color: {C_AMBER} !important; font-size: 0.8rem; font-weight: 600;
    }}
    [data-testid="stMetricValue"] {{
        color: {C_DARK} !important; font-size: 1.8rem; font-weight: 800;
    }}

    /* 交通灯 */
    .traffic-dot {{
        display: inline-block; width: 14px; height: 14px; border-radius: 50%;
        margin-right: 8px; vertical-align: middle;
    }}
    .dot-online  {{ background-color: {C_GREEN}; box-shadow: 0 0 8px {C_GREEN}66; }}
    .dot-busy    {{ background-color: {C_YELLOW}; box-shadow: 0 0 8px {C_YELLOW}66; }}
    .dot-offline {{ background-color: {C_RED}; box-shadow: 0 0 8px {C_RED}66; }}
    .dot-unknown {{ background-color: {C_OFFLINE}; }}

    /* Agent 卡片 */
    .agent-card {{
        background: {C_CARD}; border-radius: 10px; padding: 1rem;
        border-left: 4px solid {C_GOLD}; margin-bottom: 0.8rem;
        box-shadow: 0 1px 4px rgba(35,30,28,0.05);
    }}
    .agent-card h4 {{ margin: 0 0 0.3rem 0; color: {C_DARK}; font-size: 1rem; }}
    .agent-card p  {{ margin: 0; font-size: 0.82rem; color: #666; }}

    /* 进度条 */
    .step-progress {{
        display: flex; gap: 3px; margin: 0.8rem 0;
    }}
    .step-done    {{ background: {C_GREEN}; height: 10px; flex:1; border-radius: 5px; }}
    .step-running {{ background: {C_GOLD}; height: 10px; flex:1; border-radius: 5px; animation: pulse 1.2s infinite; }}
    .step-pending {{ background: #E0E0E0; height: 10px; flex:1; border-radius: 5px; }}
    .step-failed  {{ background: {C_RED}; height: 10px; flex:1; border-radius: 5px; }}
    .step-blocked {{ background: {C_RED}; height: 10px; flex:1; border-radius: 5px; animation: pulse 0.6s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.3}} }}

    /* 表格内状态徽标 */
    .badge-ok     {{ color: {C_GREEN}; font-weight: 600; }}
    .badge-warn   {{ color: {C_YELLOW}; font-weight: 600; }}
    .badge-error  {{ color: {C_RED}; font-weight: 600; }}

    /* 日志容器 */
    .log-container {{
        background: #1A1A1A; color: #E0E0E0; font-family: 'Consolas','Courier New',monospace;
        font-size: 0.82rem; padding: 1rem; border-radius: 8px;
        min-height: 33vh; max-height: 80vh; overflow-y: auto; line-height: 1.6;
        border: 1px solid #333;
    }}
    .log-line {{ white-space: pre-wrap; word-break: break-all; }}
    .log-ERROR   {{ color: #EF5350; }}
    .log-WARNING {{ color: #FFB74D; }}
    .log-INFO    {{ color: #B0BEC5; }}
    .log-DEBUG   {{ color: #78909C; }}
    .log-timestamp {{ color: #607D8B; }}

    /* 表单卡片 */
    .form-card {{
        background: {C_CARD}; border-radius: 10px; padding: 1.5rem;
        border-left: 4px solid {C_GOLD}; margin-bottom: 1rem;
    }}

    hr {{ border-color: {C_GRAY}66; }}
    .section-title {{ color: {C_DARK}; border-bottom: 2px solid {C_GOLD}; padding-bottom: 0.3rem; margin-bottom: 1rem; }}
    .nav-separator {{ color: {C_AMBER}; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 2px; margin: 0.8rem 0 0.3rem 0; padding-left: 0.5rem; }}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# 数据访问层
# ═══════════════════════════════════════════════════════════════════════

@st.cache_resource
def _get_modules():
    """惰性加载 hub_api / registry"""
    try:
        import hub_api
        from registry.workflows import list_all_spokes
        return hub_api, list_all_spokes
    except Exception:
        return None, lambda: []

def _query_age(sql: str, params=()) -> List[dict]:
    """查询 age_hub.db"""
    if not DB_AGE.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_AGE))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []

def _query_ako(sql: str, params=()) -> List[dict]:
    """查询 ako_hub.db"""
    if not DB_AKO.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_AKO))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []

def _check_http(endpoint: str, timeout: float = 3.0) -> Dict:
    """HTTP 健康检查"""
    try:
        req = urllib.request.Request(endpoint, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {"url": endpoint, "status": "ok", "code": resp.status}
    except Exception as e:
        return {"url": endpoint, "status": "error", "error": str(e)[:80]}

# ═══════════════════════════════════════════════════════════════════════
# P0-1. 系统状态总览
# ═══════════════════════════════════════════════════════════════════════
def render_overview():
    st.markdown('<h2 class="section-title">🫀 系统状态总览</h2>', unsafe_allow_html=True)

    hub_api, list_all_spokes = _get_modules()

    hub_online = False
    if hub_api:
        try:
            hub_online = bool(hub_api.hub_status())
        except Exception:
            hub_online = False

    langgraph_state = "unknown"
    try:
        from core.langgraph_master import get_graph_state, get_graph_stats
        langgraph_state = get_graph_state()
    except Exception:
        pass

    state_label = {
        "idle": "🟢 空闲", "running": "🟡 运行中",
        "error": "🔴 异常", "unknown": "⚫ 未连接"
    }

    c1, c2 = st.columns(2)
    c1.metric("AKO_Hub 主服务", "🟢 在线" if hub_online else "🔴 离线")
    c2.metric("LangGraph 状态机", state_label.get(langgraph_state, langgraph_state))

    st.divider()
    st.subheader("组件健康检查")
    endpoints = [
        ("Hub API",       "http://127.0.0.1:7862/health"),
        ("Chat",          "http://127.0.0.1:7861/health"),
        ("Knowledge",     "http://127.0.0.1:8000/health"),
        ("Quote",         "http://127.0.0.1:5000/health"),
        ("Reports",       "http://127.0.0.1:5001/health"),
        ("Business",      "http://127.0.0.1:5002/health"),
        ("FormExtractor", "http://127.0.0.1:5003/health"),
        ("Workflow",      "http://127.0.0.1:5004/health"),
        ("Console",       "http://127.0.0.1:8501/health"),
    ]
    results = [_check_http(ep) for _, ep in endpoints]
    health_rows = []
    for (name, _), r in zip(endpoints, results):
        icon = "🟢" if r["status"] == "ok" else "🔴"
        health_rows.append({
            "组件": f"{icon} {name}",
            "状态": r["status"],
            "HTTP": r.get("code", "—"),
        })
    st.dataframe(
        pd.DataFrame(health_rows),
        use_container_width=True, hide_index=True,
        column_config={"组件": "组件", "状态": "状态", "HTTP": "HTTP"}
    )


# ═══════════════════════════════════════════════════════════════════════
# P0-2. Agent 节点状态
# ═══════════════════════════════════════════════════════════════════════
def render_agents():
    st.markdown('<h2 class="section-title">🤖 Agent 节点状态</h2>', unsafe_allow_html=True)

    _, list_all_spokes = _get_modules()
    spokes = list_all_spokes()

    heartbeats = _query_ako("""
        SELECT agent_id, status, timestamp
        FROM heartbeats h1
        WHERE h1.id = (SELECT MAX(id) FROM heartbeats WHERE agent_id=h1.agent_id)
    """)
    hb_map = {r["agent_id"]: r for r in heartbeats}

    loads = _query_age("""
        SELECT trigger_agent as agent_id, COUNT(*) as running
        FROM task_queue WHERE status='running' GROUP BY trigger_agent
    """)
    load_map = {r["agent_id"]: r["running"] for r in loads}

    cols = st.columns(3)
    for i, s in enumerate(spokes):
        wid = s["workflow_id"]
        hb = hb_map.get(wid)
        load = load_map.get(wid, 0)

        if hb:
            if hb["status"] == "alive":
                dot_class = "dot-busy" if load > 0 else "dot-online"
            else:
                dot_class = "dot-offline"
            last_hb = hb["timestamp"][:19] if hb["timestamp"] else "—"
        else:
            dot_class = "dot-unknown"
            last_hb = "—"

        with cols[i % 3]:
            st.markdown(f"""
            <div class="agent-card">
                <h4><span class="traffic-dot {dot_class}"></span> {s['name']}</h4>
                <p>最后心跳: {last_hb}</p>
                <p>当前负载: {load} 任务 &nbsp;|&nbsp; 类型: {s.get('spoke_type','—')}</p>
            </div>
            """, unsafe_allow_html=True)

    with st.expander("📋 心跳历史（最近 50 条）"):
        hist = _query_ako(
            "SELECT agent_id, timestamp, status FROM heartbeats ORDER BY timestamp DESC LIMIT 50"
        )
        if hist:
            st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)
        else:
            st.info("暂无心跳记录")


# ═══════════════════════════════════════════════════════════════════════
# P0-3. Workflow 运行态
# ═══════════════════════════════════════════════════════════════════════
def render_workflow():
    st.markdown('<h2 class="section-title">⚡ Workflow 运行态</h2>', unsafe_allow_html=True)

    tasks = _query_age(
        "SELECT task_id, status, error_log, started_at, finished_at "
        "FROM task_queue WHERE workflow_id='AKO工作流' ORDER BY started_at DESC LIMIT 10"
    )

    if not tasks:
        st.info("暂无 AKO工作流 记录")
        return

    latest = tasks[0]
    sts = latest["status"]
    status_map = {
        "pending":   ("🟡 等待中", "step-pending"),
        "running":   ("🟢 执行中", "step-running"),
        "done":      ("✅ 已完成", "step-done"),
        "failed":    ("❌ 失败",   "step-failed"),
        "cancelled": ("⚫ 已取消", "step-pending"),
    }
    status_label, step_class = status_map.get(sts, (sts, "step-pending"))

    blocking_agent = "—"
    if sts == "running":
        sub_tasks = _query_age(
            "SELECT trigger_agent, status, started_at FROM task_queue "
            "WHERE workflow_id='AKO工作流' AND status='running' AND trigger_agent IS NOT NULL "
            "ORDER BY started_at ASC"
        )
        if sub_tasks:
            blocking_agent = sub_tasks[0]["trigger_agent"]

    st.markdown(f"**当前状态**: {status_label}")
    st.markdown(f"**阻塞节点**: {blocking_agent}")

    wf_steps = ["意图解析", "设计生成", "图纸审查", "报价计算", "成果汇总"]
    if sts == "done":
        bar_html = '<div class="step-progress">'
        bar_html += '<div class="step-done"></div>' * len(wf_steps)
        bar_html += '</div>'
    elif sts == "failed":
        bar_html = '<div class="step-progress">'
        bar_html += '<div class="step-failed"></div>' * len(wf_steps)
        bar_html += '</div>'
    elif sts == "running":
        done_agents = _query_age(
            "SELECT DISTINCT trigger_agent FROM task_queue "
            "WHERE workflow_id='AKO工作流' AND status='done'"
        )
        running_agents = _query_age(
            "SELECT DISTINCT trigger_agent FROM task_queue "
            "WHERE workflow_id='AKO工作流' AND status='running'"
        )
        done_count = len(done_agents)
        running_count = len(running_agents)

        bar_html = '<div class="step-progress">'
        bar_html += '<div class="step-done"></div>' * done_count
        bar_html += '<div class="step-blocked"></div>' * (1 if running_count > 0 else 0)
        bar_html += '<div class="step-pending"></div>' * max(0, len(wf_steps) - done_count - (1 if running_count > 0 else 0))
        bar_html += '</div>'
    else:
        bar_html = '<div class="step-progress">'
        bar_html += '<div class="step-pending"></div>' * len(wf_steps)
        bar_html += '</div>'

    st.markdown(bar_html, unsafe_allow_html=True)
    st.caption(" | ".join(wf_steps))

    if sts == "failed" and latest.get("error_log"):
        st.error(f"错误: {latest['error_log'][:500]}")

    st.divider()
    st.subheader("最近 AKO工作流 任务")
    rows = []
    for t in tasks:
        rows.append({
            "任务ID": (t["task_id"] or "")[:20],
            "状态": t["status"],
            "开始": (t["started_at"] or "")[:19],
            "结束": (t["finished_at"] or "")[:19],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# P0-4. 任务队列
# ═══════════════════════════════════════════════════════════════════════
def render_task_queue():
    st.markdown('<h2 class="section-title">📋 任务队列</h2>', unsafe_allow_html=True)

    pending = _query_age("SELECT COUNT(*) as n FROM task_queue WHERE status='pending'")
    running = _query_age("SELECT COUNT(*) as n FROM task_queue WHERE status='running'")
    failed  = _query_age("SELECT COUNT(*) as n FROM task_queue WHERE status='failed'")

    pn = pending[0]["n"] if pending else 0
    rn = running[0]["n"] if running else 0
    fn = failed[0]["n"] if failed else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("待分发", pn)
    c2.metric("执行中", rn)
    c3.metric("失败", fn)

    st.divider()

    tasks = _query_age(
        "SELECT task_id, workflow_id, trigger_agent, status, started_at, error_log "
        "FROM task_queue ORDER BY started_at DESC LIMIT 50"
    )

    if not tasks:
        st.info("任务队列为空")
        return

    rows = []
    for t in tasks:
        tid = (t["task_id"] or "")[:20]
        status_str = t["status"]
        if status_str == "done":
            st_icon = "✅"
        elif status_str == "running":
            st_icon = "🟢"
        elif status_str == "failed":
            st_icon = "❌"
        elif status_str == "pending":
            st_icon = "🟡"
        else:
            st_icon = "⚫"

        rows.append({
            "任务ID": tid,
            "工作流": t["workflow_id"] or "—",
            "绑定Agent": t["trigger_agent"] or "未分配",
            "状态": f"{st_icon} {status_str}",
            "创建时间": (t["started_at"] or "")[:19],
            "错误": (t["error_log"] or "")[:80],
        })

    df = pd.DataFrame(rows)
    event = st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "任务ID": "任务ID",
            "工作流": "工作流",
            "绑定Agent": "绑定 Agent",
            "状态": "状态",
            "创建时间": "创建时间",
            "错误": "错误信息",
        }
    )

    hub_api, _ = _get_modules()
    if hub_api and event and hasattr(event, "selection") and event.selection.get("rows"):
        idx = event.selection["rows"][0]
        if idx < len(tasks):
            tid = tasks[idx]["task_id"]
            with st.spinner("加载任务详情…"):
                detail = hub_api.get_task_detail(tid)
            if detail:
                with st.expander(f"📄 详情: {tid[:20]}…"):
                    st.json(detail)


# ═══════════════════════════════════════════════════════════════════════
# P1-1. 任务提交/触发
# ═══════════════════════════════════════════════════════════════════════
def render_task_submit():
    st.markdown('<h2 class="section-title">🚀 任务提交/触发</h2>', unsafe_allow_html=True)

    hub_api, list_all_spokes = _get_modules()
    spokes = list_all_spokes()

    with st.container():
        st.markdown('<div class="form-card">', unsafe_allow_html=True)

        # ── 任务描述输入 ──
        intent = st.text_area(
            "任务描述", placeholder="输入意图描述，Hub 会自动解析并路由到对应 Agent…",
            height=80, key="submit_intent"
        )

        c1, c2 = st.columns(2)
        with c1:
            project_tag = st.text_input("项目标签", placeholder="如 taoli、ako_demo", key="submit_project")

        with c2:
            # 直接指定 Agent 快捷入口
            agent_options = ["自动路由"] + [s["name"] for s in spokes]
            selected_agent = st.selectbox("直接指定 Agent（可选）", agent_options, key="submit_agent")

        c1b, c2b = st.columns([1, 3])
        with c1b:
            submitted = st.button("🚀 提交任务", use_container_width=True, type="primary")

        st.markdown('</div>', unsafe_allow_html=True)

        if submitted and intent.strip():
            with st.spinner("提交中…"):
                try:
                    payload = {"intent": intent.strip()}
                    if project_tag.strip():
                        payload["project_tag"] = project_tag.strip()
                    if selected_agent != "自动路由":
                        # 查找对应的 workflow_id
                        for s in spokes:
                            if s["name"] == selected_agent:
                                payload["target_agent"] = s["workflow_id"]
                                break

                    if hub_api:
                        result = hub_api.submit_task(payload, trigger="dashboard")
                        if result.get("status") == "done":
                            st.success(f"任务提交成功 — {result.get('task_id', '—')}")
                            with st.expander("📄 查看结果"):
                                st.json(result)
                        elif result.get("status") == "failed":
                            st.error(f"任务失败: {result.get('error_log', '未知错误')[:300]}")
                        else:
                            st.info(f"任务已入队，状态: {result.get('status', '—')}")
                    else:
                        st.warning("hub_api 未加载，无法提交任务")
                except Exception as e:
                    st.error(f"提交异常: {str(e)[:300]}")
        elif submitted:
            st.warning("请输入任务描述")


# ═══════════════════════════════════════════════════════════════════════
# P1-2. 知识库检索
# ═══════════════════════════════════════════════════════════════════════
def render_knowledge():
    st.markdown('<h2 class="section-title">📚 知识库检索</h2>', unsafe_allow_html=True)

    hub_api, _ = _get_modules()

    # ── Collection 列表 ──
    collections = []
    if hub_api:
        try:
            collections = hub_api.list_knowledge_bases()
        except Exception:
            pass

    # 同时从本地 DB 补数据（独立于 hub_api 在线状态）
    db_kbs = _query_age("SELECT * FROM knowledge_base ORDER BY updated_at DESC")

    # ── 搜索框 ──
    search_term = st.text_input("🔍 搜索知识库", placeholder="输入关键词检索 Collection 和文档…", key="kb_search")

    # ── 嵌入统计 ──
    c1, c2, c3, c4 = st.columns(4)
    total_kb = len(db_kbs) if db_kbs else len(collections)
    c1.metric("知识库总数", total_kb)
    c2.metric("嵌入模型", "bge-m3")
    # 最近更新
    last_update = "—"
    if db_kbs:
        last_update = db_kbs[0].get("updated_at", "—")[:19]
    c3.metric("最近更新", last_update)
    # 嵌入状态（简化：有 collection 即成功）
    embed_ok = len(db_kbs) if db_kbs else (len(collections) if collections else 0)
    c4.metric("嵌入成功", embed_ok)

    st.divider()

    # ── Collection 表格 ──
    st.subheader("知识库列表")
    if db_kbs:
        rows = []
        for kb in db_kbs:
            rows.append({
                "KB ID": kb.get("kb_id", "—"),
                "名称": kb.get("kb_name", "—"),
                "所属 Agent": kb.get("agent_name", "—"),
                "Collection": kb.get("collection_name", "—"),
                "嵌入模型": kb.get("embedding_model", "bge-m3"),
                "最近更新": (kb.get("updated_at", "—") or "—")[:19],
            })

        # 搜索过滤
        if search_term:
            rows = [r for r in rows if search_term.lower() in str(r).lower()]

        st.dataframe(
            pd.DataFrame(rows), use_container_width=True, hide_index=True,
            column_config={
                "KB ID": "KB ID", "名称": "名称", "所属 Agent": "所属 Agent",
                "Collection": "Collection", "嵌入模型": "嵌入模型", "最近更新": "最近更新",
            }
        )
    elif collections:
        st.dataframe(pd.DataFrame(collections), use_container_width=True, hide_index=True)
    else:
        st.info("暂无知识库数据（knowledge_base 表为空且 hub_api 无返回）")

    # ── 最近入库文档 ──
    st.divider()
    st.subheader("最近入库文档")
    recent_files = _query_age(
        "SELECT file_id, source_agent, rel_path, file_type, project_tag, created_at "
        "FROM file_registry ORDER BY created_at DESC LIMIT 20"
    )
    if recent_files:
        frows = []
        for f in recent_files:
            frows.append({
                "文件ID": (f["file_id"] or "—")[:30],
                "来源 Agent": f.get("source_agent", "—"),
                "路径": f.get("rel_path", "—"),
                "类型": f.get("file_type", "—"),
                "项目": f.get("project_tag", "—"),
                "创建时间": (f.get("created_at", "—") or "—")[:19],
            })
        st.dataframe(pd.DataFrame(frows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无文件记录")


# ═══════════════════════════════════════════════════════════════════════
# P1-3. 同步监控
# ═══════════════════════════════════════════════════════════════════════
def render_sync():
    st.markdown('<h2 class="section-title">🔄 同步监控</h2>', unsafe_allow_html=True)

    hub_api, _ = _get_modules()

    # ── sync_root 状态 ──
    sync_root = "D:\\BaiduSyncdisk\\AKO_Hub"
    try:
        from core.hub_db import HubDB  # noqa: F811
        paths = {
            "sync_root": str(Path("D:/BaiduSyncdisk/AKO_Hub")),
            "db_path": str(Path("D:/BaiduSyncdisk/AKO_Hub/age_hub.db")),
        }
    except Exception:
        paths = {"sync_root": sync_root}

    sync_root_display = paths.get("sync_root", sync_root)
    root_exists = Path(sync_root_display).exists() if sync_root_display else False

    c1, c2, c3 = st.columns(3)
    c1.metric("Sync Root", "🟢 可访问" if root_exists else "🔴 不可访问")
    c1.caption(sync_root_display)

    # ── 同步统计 ──
    sync_stats = {"match": 0, "mismatch": 0, "missing": 0}
    if DB_AGE.exists():
        stats_rows = _query_age(
            "SELECT status, COUNT(*) as cnt FROM sync_log GROUP BY status"
        )
        for r in stats_rows:
            sync_stats[r["status"]] = r["cnt"]

    c2.metric("已同步", sync_stats["match"], delta=None)
    c3.metric("冲突/缺失", f"{sync_stats['mismatch']} / {sync_stats['missing']}",
              delta=f"{sync_stats['mismatch'] + sync_stats['missing']}" if (sync_stats['mismatch'] + sync_stats['missing']) > 0 else None)

    # ── 外部接口健康 ──
    st.divider()
    st.subheader("外部接口健康检查")
    ext_endpoints = [
        ("百度云盘 API", "https://pan.baidu.com"),
        ("Ollama",        "http://127.0.0.1:11434"),
        ("ComfyUI",       "http://127.0.0.1:8188"),
    ]
    ext_results = [_check_http(ep) for _, ep in ext_endpoints]
    ext_rows = []
    for (name, _), r in zip(ext_endpoints, ext_results):
        icon = "🟢" if r["status"] == "ok" else "🔴"
        ext_rows.append({
            "服务": f"{icon} {name}",
            "状态": r["status"],
            "详情": r.get("code", r.get("error", "—")),
        })
    st.dataframe(pd.DataFrame(ext_rows), use_container_width=True, hide_index=True)

    # ── 文件变更事件 ──
    st.divider()
    st.subheader("文件变更事件（sync_log）")
    sync_events = _query_age(
        "SELECT file_id, machine_id, status, checked_at FROM sync_log ORDER BY checked_at DESC LIMIT 30"
    )
    if sync_events:
        erows = []
        for e in sync_events:
            sicon = {"match": "✅", "mismatch": "⚠️", "missing": "❌"}.get(e["status"], "—")
            erows.append({
                "文件ID": (e["file_id"] or "—")[:30],
                "机器": e.get("machine_id", "—"),
                "同步状态": f"{sicon} {e['status']}",
                "检查时间": (e.get("checked_at", "—") or "—")[:19],
            })
        st.dataframe(pd.DataFrame(erows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无同步事件记录")


# ═══════════════════════════════════════════════════════════════════════
# P1-4. 日志流
# ═══════════════════════════════════════════════════════════════════════
def render_logs():
    st.markdown('<h2 class="section-title">📜 实时日志流</h2>', unsafe_allow_html=True)

    # ── 过滤控制 ──
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        level_filter = st.selectbox("日志级别", ["ALL", "ERROR", "WARNING", "INFO", "DEBUG"], key="log_level")
    with c2:
        log_source = st.selectbox("来源", ["全部", "Agent 输出", "路由决策", "任务错误", "告警"], key="log_source")
    with c3:
        auto_refresh = st.checkbox("自动刷新", value=False, key="log_auto_refresh")

    if auto_refresh:
        st.caption("⏱ 每 10 秒自动刷新")

    # ── 收集日志 ──
    log_lines = []

    # 1. Agent 日志 (logs 表)
    logs_sql = "SELECT agent_id, level, message, context, timestamp FROM logs"
    conditions = []
    if auto_refresh:
        logs_sql += " WHERE timestamp > datetime('now', '-15 minutes')"
    if level_filter != "ALL":
        conditions.append(f"level = '{level_filter}'")
    if auto_refresh and conditions:
        logs_sql += " AND " + " AND ".join(conditions)
    elif conditions:
        logs_sql += " WHERE " + " AND ".join(conditions)
    logs_sql += " ORDER BY timestamp DESC LIMIT 200"

    db_logs = _query_ako(logs_sql)
    for row in reversed(db_logs):
        log_lines.append({
            "ts": (row.get("timestamp", "") or "")[:19],
            "level": row.get("level", "INFO"),
            "source": row.get("agent_id", "—"),
            "message": row.get("message", ""),
            "category": "Agent 输出",
        })

    # 2. 任务错误 (task_queue error_log)
    task_errors = _query_age(
        "SELECT task_id, trigger_agent, error_log, finished_at as ts FROM task_queue "
        "WHERE error_log IS NOT NULL AND error_log != '' ORDER BY finished_at DESC LIMIT 50"
    )
    for row in reversed(task_errors):
        log_lines.append({
            "ts": (row.get("ts", "") or "")[:19],
            "level": "ERROR",
            "source": row.get("trigger_agent", "task") or "task",
            "message": row.get("error_log", "")[:500],
            "category": "任务错误",
        })

    # 3. 告警 (alerts 表)
    alerts = _query_ako(
        "SELECT agent_id, alert_type, severity, message, created_at as ts FROM alerts "
        "ORDER BY created_at DESC LIMIT 50"
    )
    for row in reversed(alerts):
        log_lines.append({
            "ts": (row.get("ts", "") or "")[:19],
            "level": row.get("severity", "WARNING").upper(),
            "source": row.get("agent_id", "alert") or "alert",
            "message": f"[{row.get('alert_type', '—')}] {row.get('message', '')}",
            "category": "告警",
        })

    # ── 来源过滤 ──
    if log_source == "Agent 输出":
        log_lines = [l for l in log_lines if l["category"] == "Agent 输出"]
    elif log_source == "路由决策":
        log_lines = [l for l in log_lines if l["category"] == "Agent 输出" and "route" in l["message"].lower()]
    elif log_source == "任务错误":
        log_lines = [l for l in log_lines if l["category"] == "任务错误"]
    elif log_source == "告警":
        log_lines = [l for l in log_lines if l["category"] == "告警"]

    # ── 级别过滤（对合并后的日志再过滤一次） ──
    if level_filter != "ALL":
        log_lines = [l for l in log_lines if l["level"] == level_filter]

    # ── 渲染日志容器 ──
    st.markdown(f"共 {len(log_lines)} 条日志", help="上限 300 条")
    if not log_lines:
        st.info("暂无日志")
        return

    html = '<div class="log-container">'
    for line in log_lines[-200:]:  # 最多显示 200 条
        lvl = line["level"]
        ts = line["ts"]
        src = line["source"]
        msg = line["message"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html += f'<div class="log-line"><span class="log-timestamp">{ts}</span> '
        html += f'<span class="log-{lvl}">[{lvl}]</span> '
        html += f'<span>[{src}]</span> {msg}</div>\n'
    html += '</div>'

    st.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# P2-1. 任务历史
# ═══════════════════════════════════════════════════════════════════════
def render_task_history():
    st.markdown('<h2 class="section-title">📊 任务历史</h2>', unsafe_allow_html=True)

    hub_api, list_all_spokes = _get_modules()
    spokes = list_all_spokes()
    agent_names = [s["name"] for s in spokes]
    agent_wid_map = {s["workflow_id"]: s["name"] for s in spokes}

    # Agent 过滤下拉
    c1, c2 = st.columns([2, 1])
    with c1:
        agent_filter = st.selectbox("按 Agent 过滤", ["全部"] + agent_names, key="hist_agent")
    with c2:
        limit = st.selectbox("显示条数", [20, 50, 100], index=1, key="hist_limit")

    # 条件构建
    where = "WHERE status IN ('done', 'failed')"
    if agent_filter != "全部":
        wid = next((s["workflow_id"] for s in spokes if s["name"] == agent_filter), None)
        if wid:
            where += f" AND trigger_agent = '{wid}'"

    tasks = _query_age(
        f"SELECT task_id, workflow_id, trigger_agent, status, started_at, finished_at, error_log "
        f"FROM task_queue {where} ORDER BY started_at DESC LIMIT {limit}"
    )

    if not tasks:
        st.info("暂无历史任务记录")
        return

    # 统计
    done_count = sum(1 for t in tasks if t["status"] == "done")
    fail_count = sum(1 for t in tasks if t["status"] == "failed")
    c1, c2, c3 = st.columns(3)
    c1.metric("已完成", done_count)
    c2.metric("失败", fail_count)
    c3.metric("平均耗时", _calc_avg_duration(tasks))

    st.divider()

    rows = []
    for t in tasks:
        tid = (t["task_id"] or "")[:24]
        agent_display = agent_wid_map.get(t["trigger_agent"], t["trigger_agent"] or "—")
        status_icon = "✅" if t["status"] == "done" else "❌"
        duration = _calc_duration(t["started_at"], t["finished_at"])
        rows.append({
            "任务ID": tid,
            "工作流": t["workflow_id"] or "—",
            "最终 Agent": agent_display,
            "状态": f"{status_icon} {t['status']}",
            "开始": (t["started_at"] or "")[:19],
            "耗时": duration,
        })

    df = pd.DataFrame(rows)
    event = st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "任务ID": "任务ID", "工作流": "工作流", "最终 Agent": "最终 Agent",
            "状态": "状态", "开始": "开始时间", "耗时": "执行时长",
        }
    )

    # 点击查看输出摘要
    if hub_api and event is not None and hasattr(event, "selection") and event.selection.get("rows"):
        idx = event.selection["rows"][0]
        if idx < len(tasks):
            tid = tasks[idx]["task_id"]
            with st.spinner("加载任务详情…"):
                try:
                    detail = hub_api.get_task_detail(tid)
                    if detail:
                        with st.expander(f"📄 输出摘要: {tid[:24]}…"):
                            if isinstance(detail, dict):
                                summary = detail.get("summary", detail.get("output", ""))
                                st.markdown(f"**状态**: {detail.get('status', '—')}")
                                if summary:
                                    st.text(summary[:2000])
                                st.json({k: v for k, v in detail.items() if k not in ("summary", "output")})
                            else:
                                st.json(detail)
                except Exception as e:
                    st.warning(f"无法加载详情: {e}")


def _calc_duration(started: Optional[str], finished: Optional[str]) -> str:
    """计算任务执行时长"""
    if not started or not finished:
        return "—"
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        s = datetime.strptime(started[:19], fmt)
        f = datetime.strptime(finished[:19], fmt)
        secs = (f - s).total_seconds()
        if secs < 60:
            return f"{secs:.0f}s"
        elif secs < 3600:
            return f"{secs / 60:.1f}min"
        else:
            return f"{secs / 3600:.1f}h"
    except Exception:
        return "—"


def _calc_avg_duration(tasks: List[dict]) -> str:
    """计算平均耗时"""
    valid = []
    for t in tasks:
        d = _calc_duration(t["started_at"], t["finished_at"])
        if d != "—":
            valid.append(d)
    if not valid:
        return "—"
    # 简单返回第一条有效记录作为参考
    return valid[0] if len(valid) == 1 else f"共 {len(valid)} 条"


# ═══════════════════════════════════════════════════════════════════════
# P2-2. 错误追踪
# ═══════════════════════════════════════════════════════════════════════
def render_error_tracking():
    st.markdown('<h2 class="section-title">❌ 错误追踪</h2>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🔴 失败任务", "⚠️ Agent 异常退出", "🧩 嵌入失败"])

    with tab1:
        _render_failed_tasks()
    with tab2:
        _render_agent_exits()
    with tab3:
        _render_embed_failures()


def _render_failed_tasks():
    """失败任务详情列表"""
    failed = _query_age(
        "SELECT task_id, workflow_id, trigger_agent, started_at, finished_at, error_log "
        "FROM task_queue WHERE status='failed' ORDER BY started_at DESC LIMIT 50"
    )
    if not failed:
        st.info("没有失败任务")
        return

    st.metric("失败任务总数", len(failed))

    for f in failed:
        tid = (f["task_id"] or "")[:24]
        agent = f["trigger_agent"] or "—"
        err_msg = (f["error_log"] or "无错误信息")[:300]
        with st.expander(f"❌ {tid} — {agent} — {(f['started_at'] or '')[:19]}"):
            st.markdown(f"**工作流**: {f['workflow_id'] or '—'}")
            st.markdown(f"**Agent**: {agent}")
            st.markdown(f"**时间**: {(f['started_at'] or '')[:19]} → {(f['finished_at'] or '')[:19]}")
            st.error(err_msg)


def _render_agent_exits():
    """Agent 异常退出记录（来自 alerts 表）"""
    alerts = _query_ako(
        "SELECT id, level, agent_id, message, created_at "
        "FROM alerts WHERE level IN ('error', 'critical') "
        "ORDER BY created_at DESC LIMIT 50"
    )
    if not alerts:
        st.info("没有告警记录")
        return

    st.metric("告警总数", len(alerts))

    rows = []
    for a in alerts:
        rows.append({
            "ID": a["id"],
            "级别": a["level"],
            "Agent": a["agent_id"] or "—",
            "消息": (a["message"] or "")[:120],
            "时间": (a["created_at"] or "")[:19],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_embed_failures():
    """知识库嵌入失败条目"""
    # 从 knowledge_base 表查找嵌入异常
    kb_errors = _query_age(
        "SELECT id, file_name, status, error_msg, created_at "
        "FROM knowledge_base WHERE status = 'error' "
        "ORDER BY created_at DESC LIMIT 50"
    )

    if not kb_errors:
        st.info("没有嵌入失败记录")
        return

    st.metric("嵌入失败", len(kb_errors))

    rows = []
    for e in kb_errors:
        rows.append({
            "ID": e["id"],
            "文件": e["file_name"] or "—",
            "状态": e["status"],
            "错误": (e["error_msg"] or "")[:100],
            "时间": (e["created_at"] or "")[:19],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# P2-3. 配置面板
# ═══════════════════════════════════════════════════════════════════════
def render_config():
    st.markdown('<h2 class="section-title">⚙️ 配置面板</h2>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["🔗 API 端点", "🧠 模型路由", "📦 知识库参数", "🔧 Spoke 注册表"])

    with tab1:
        _render_api_endpoints()
    with tab2:
        _render_model_routes()
    with tab3:
        _render_kb_params()
    with tab4:
        _render_spoke_registry()


def _render_api_endpoints():
    """Hub API 端点列表"""
    try:
        from core.ako_config import get_config
        cfg = get_config()
        ports = cfg.get("service_ports", {})
    except Exception:
        ports = {}

    endpoints = [
        ("Hub API",    f"http://127.0.0.1:{ports.get('hub', 7862)}"),
        ("Chat",       f"http://127.0.0.1:{ports.get('chat', 7861)}"),
        ("Knowledge",  f"http://127.0.0.1:{ports.get('knowledge', 8000)}"),
        ("Console",    f"http://127.0.0.1:{ports.get('console', 8501)}"),
        ("SD (Comfy)", f"http://127.0.0.1:{ports.get('sd', 7860)}"),
        ("Quote",      f"http://127.0.0.1:{ports.get('quote', 5000)}"),
    ]

    results = []
    for name, url in endpoints:
        health = _check_http(f"{url}/health", timeout=2.0)
        icon = "🟢" if health["status"] == "ok" else "🔴"
        results.append({
            "组件": f"{icon} {name}",
            "地址": url,
            "状态": health["status"],
            "HTTP": health.get("code", "—"),
        })

    st.dataframe(
        pd.DataFrame(results), use_container_width=True, hide_index=True,
        column_config={"组件": "组件", "地址": "端点地址", "状态": "状态", "HTTP": "HTTP"}
    )

    # 当前 Hub 状态
    st.divider()
    st.subheader("Hub 连接状态")
    hub_api, _ = _get_modules()
    if hub_api:
        try:
            status = hub_api.hub_status()
            st.json(status if isinstance(status, dict) else {"status": str(status)})
        except Exception as e:
            st.error(f"Hub 不可达: {e}")
    else:
        st.warning("hub_api 未加载")


def _render_model_routes():
    """模型路由规则展示"""
    st.markdown("### 路由链配置")

    # 从 ako_geo/config.py 读取路由
    routes = {}
    try:
        from ako_geo.config import LLM_ROUTE_OUTLINE, LLM_ROUTE_FORMAT_LONG, LLM_ROUTE_FORMAT_SHORT
        routes = {
            "大纲生成 (Outline)": LLM_ROUTE_OUTLINE,
            "长文本润色 (Format Long)": LLM_ROUTE_FORMAT_LONG,
            "短文本润色 (Format Short)": LLM_ROUTE_FORMAT_SHORT,
        }
    except ImportError:
        st.warning("ako_geo.config 不可用，显示默认配置")
        routes = {
            "大纲生成 (Outline)": {"primary": "deepseek", "fallback": ["kimi", "ollama"]},
            "长文本润色 (Format Long)": {"primary": "kimi", "fallback": ["deepseek", "ollama"]},
            "短文本润色 (Format Short)": {"primary": "qwen", "fallback": ["kimi", "ollama"]},
        }

    rows = []
    for name, route in routes.items():
        primary = route.get("primary", "—")
        fallback = " → ".join(route.get("fallback", []))
        rows.append({
            "场景": name,
            "首选模型": primary,
            "降级链": fallback or "—",
        })

    st.dataframe(
        pd.DataFrame(rows), use_container_width=True, hide_index=True,
        column_config={"场景": "应用场景", "首选模型": "首选模型", "降级链": "降级链路"}
    )

    st.caption("路由策略: Primary → Fallback 链式降级，Ollama 为最终兜底")

    # 模型列表
    st.divider()
    st.markdown("### 可用模型")
    try:
        from core.ako_config.settings import _LLM_ENV_MAP, ModelRouting
        env_rows = [{"模型": k, "环境变量": v} for k, v in _LLM_ENV_MAP.items()]
        st.dataframe(pd.DataFrame(env_rows), use_container_width=True, hide_index=True)
        st.caption(f"创意模型: {ModelRouting.creative or '—'} | 降级模型: {ModelRouting.fallback or '—'}")
    except ImportError:
        st.info("settings 模块不可用")


def _render_kb_params():
    """知识库参数展示"""
    try:
        from core.ako_config import get_config
        cfg = get_config()
    except Exception:
        cfg = {}

    # 分块参数
    st.markdown("### 分块参数")
    c1, c2, c3 = st.columns(3)
    chunking = cfg.get("chunking", {})
    c1.metric("Chunk Size", chunking.get("size", 768))
    c2.metric("Overlap", chunking.get("overlap", 128))
    retrieval = cfg.get("retrieval_mode", "hybrid")
    c3.metric("检索模式", retrieval)

    # 混合权重
    if retrieval == "hybrid":
        weights = cfg.get("hybrid_weights", {})
        st.markdown("### 混合检索权重")
        w1, w2, w3 = st.columns(3)
        w1.metric("Dense", f"{weights.get('dense', 0.33):.2f}")
        w2.metric("Sparse", f"{weights.get('sparse', 0.33):.2f}")
        w3.metric("ColBERT", f"{weights.get('colbert', 0.34):.2f}")

    # Collection 列表
    st.divider()
    st.markdown("### Knowledge Base Collections")
    collections = cfg.get("kb_collections", [])
    if collections:
        rows = [{"名称": c.get("name", c) if isinstance(c, dict) else c} for c in collections]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("未配置 kb_collections")

    # 同步根路径
    st.divider()
    sync_root = cfg.get("sync_root", "—")
    st.markdown(f"**Sync Root**: `{sync_root}`")


def _render_spoke_registry():
    """Spoke 注册表一览"""
    _, list_all_spokes = _get_modules()
    spokes = list_all_spokes()

    if not spokes:
        st.info("未找到已注册 Spoke")
        return

    st.metric("已注册 Spoke 数", len(spokes))

    rows = []
    for s in spokes:
        rows.append({
            "名称": s.get("name", "—"),
            "Workflow ID": s.get("workflow_id", "—"),
            "类型": s.get("spoke_type", "—"),
            "描述": s.get("description", "—")[:60],
        })

    st.dataframe(
        pd.DataFrame(rows), use_container_width=True, hide_index=True,
        column_config={
            "名称": "名称", "Workflow ID": "Workflow ID",
            "类型": "类型", "描述": "描述",
        }
    )

    # 路由规则摘要
    st.divider()
    st.markdown("### 路由规则摘要")
    try:
        import yaml
        rules_path = PROJECT_ROOT / "config" / "routing_rules.yaml"
        if rules_path.exists():
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = yaml.safe_load(f)
            composite = rules.get("composite_tasks", [])
            keywords = rules.get("keyword_routes", [])
            st.markdown(f"**复合任务**: {len(composite)} 条 | **关键词路由**: {len(keywords)} 条")
            with st.expander("查看路由关键字"):
                kw_rows = [{"关键词": k.get("keywords", []), "Agent": k.get("target", "—"), "置信度": k.get("confidence", "—")} for k in keywords]
                st.dataframe(pd.DataFrame(kw_rows), use_container_width=True, hide_index=True)
        else:
            st.info("routing_rules.yaml 不存在")
    except Exception as e:
        st.warning(f"无法读取路由规则: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 主应用：导航 + 路由
# ═══════════════════════════════════════════════════════════════════════
PAGES = [
    # P0 核心监控
    ("🫀", "系统状态总览", render_overview),
    ("🤖", "Agent 节点状态",  render_agents),
    ("⚡", "Workflow 运行态",  render_workflow),
    ("📋", "任务队列",        render_task_queue),
    # P1 运维操作
    ("🚀", "任务提交/触发",   render_task_submit),
    ("📚", "知识库检索",      render_knowledge),
    ("🔄", "同步监控",        render_sync),
    ("📜", "日志流",          render_logs),
    # P2 数据分析
    ("📊", "任务历史",        render_task_history),
    ("❌", "错误追踪",        render_error_tracking),
    ("⚙️", "配置面板",        render_config),
]
PAGE_OPTIONS = [f"{icon} {name}" for icon, name, _ in PAGES]
PAGE_MAP = {f"{icon} {name}": fn for icon, name, fn in PAGES}

if "nav_page" not in st.session_state:
    st.session_state.nav_page = PAGE_OPTIONS[0]

with st.sidebar:
    st.markdown("## 🏗️ AKO Hub")
    st.markdown("*运维仪表盘 v3.2*")
    st.divider()

    # P0/P1/P2 分组导航
    p0_count = 4
    p1_count = 4
    p2_count = 3

    st.markdown('<p class="nav-separator">P0 · 核心监控</p>', unsafe_allow_html=True)
    st.radio(
        "nav", PAGE_OPTIONS,
        label_visibility="collapsed", key="nav_page",
        index=PAGE_OPTIONS.index(st.session_state.nav_page)
        if st.session_state.nav_page in PAGE_OPTIONS else 0
    )
    st.divider()
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"© AKObuild | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

render_func = PAGE_MAP.get(st.session_state.nav_page, render_overview)
render_func()
