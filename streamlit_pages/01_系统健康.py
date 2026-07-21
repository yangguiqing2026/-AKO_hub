"""
01_系统健康.py — Streamlit 仪表盘：AKO 系统健康监控。

展示所有 Agent 在线状态、资源使用、告警列表。
文档编号: AGE-TECH-AKO-HUB-020 §Dashboard
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd


# ── AKO 品牌色常量 ─────────────────────────────────────────────────
AKO_CREAM = "#EBDAB9"      # 奶油金 — 主色，大面积底色
AKO_GRAY  = "#C3BEB4"      # 冷暖灰 — 背景/过渡色
AKO_DARK  = "#231E1C"      # 深棕黑 — 稳重锚点，线条
AKO_AMBER = "#A08C64"      # 琥珀金 — 辅助色，点缀
AKO_GOLD  = "#B99B5F"      # 熔金 — 标题，高亮
AKO_CARD  = "#F7F3E8"      # 卡片底色 — 暖白（忌纯白 #FFF）


# ── 页面配置 ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="系统健康 — AKO Hub",
    page_icon="🫀",
    layout="wide",
)

# ── 注入品牌样式 ───────────────────────────────────────────────────
st.markdown(f"""
<style>
    /* ── 全局 ── */
    .stApp {{
        background-color: {AKO_CREAM};
    }}

    /* ── 标题 ── */
    h1, h2, h3 {{
        color: {AKO_GOLD} !important;
        font-weight: 700 !important;
    }}
    h1 {{
        border-bottom: 3px solid {AKO_AMBER};
        padding-bottom: 0.45rem;
    }}

    /* ── 指标卡片 ── */
    [data-testid="stMetric"] {{
        background: {AKO_CARD};
        border-radius: 10px;
        padding: 1rem;
        box-shadow: 0 1px 6px rgba(35, 30, 28, 0.06);
        border-left: 4px solid {AKO_GOLD};
    }}
    [data-testid="stMetricLabel"] p {{
        color: {AKO_AMBER} !important;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    [data-testid="stMetricValue"] {{
        color: {AKO_DARK} !important;
        font-size: 1.8rem;
        font-weight: 800;
    }}
    [data-testid="stMetricDelta"] {{
        font-weight: 600;
    }}

    /* ── 分割线 ── */
    hr {{
        border-color: {AKO_GRAY}66;
    }}

    /* ── 侧边栏 ── */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {AKO_CARD} 0%, {AKO_CREAM} 100%);
        border-right: 1px solid {AKO_GRAY}66;
    }}
    [data-testid="stSidebar"] .st-caption {{
        color: {AKO_AMBER} !important;
    }}

    /* ── DataFrame 表头 ── */
    [data-testid="stDataFrame"] th {{
        background-color: {AKO_DARK} !important;
        color: {AKO_CREAM} !important;
        font-weight: 600;
    }}
    [data-testid="stDataFrame"] td {{
        color: {AKO_DARK};
    }}

    /* ── Expander 告警卡片 ── */
    [data-testid="stExpander"] {{
        border: 1px solid {AKO_GRAY}88;
        border-radius: 8px;
        overflow: hidden;
        background: {AKO_CARD};
    }}
    details[open] summary {{
        border-bottom: 1px solid {AKO_GRAY}66;
    }}

    /* ── 按钮 ── */
    .stButton > button {{
        border-radius: 6px;
        font-weight: 600;
        transition: all 0.2s;
    }}
    .stButton > button:hover {{
        box-shadow: 0 2px 8px rgba(35, 30, 28, 0.12);
    }}

    /* ── info/success 容器 ── */
    [data-testid="stInfo"] {{
        background: {AKO_CARD};
    }}
    [data-testid="stSuccess"] {{
        background: {AKO_CARD};
        border-left: 4px solid {AKO_GOLD};
    }}
</style>
""", unsafe_allow_html=True)


st.title("系统健康监控")
st.caption("心跳状态 · 资源使用 · 告警一览")


# ── 数据库连接 ─────────────────────────────────────────────────────
@st.cache_resource(ttl=10)
def _get_conn():
    db_path = PROJECT_ROOT / "ako_hub.db"
    conn = sqlite3.connect(str(db_path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


conn = _get_conn()


# ── 数据加载函数 ───────────────────────────────────────────────────

def load_agents_status() -> List[Dict[str, Any]]:
    """加载所有 Agent 当前状态。"""
    try:
        cur = conn.execute("""
            SELECT
                a.agent_id, a.display_name, a.agent_type,
                h.timestamp AS last_heartbeat, h.status,
                h.cpu_percent, h.memory_mb, h.disk_percent,
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
        return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        st.error(f"数据加载失败: {e}")
        return []


def load_recent_alerts(limit: int = 20) -> List[Dict[str, Any]]:
    """加载最近告警。"""
    try:
        cur = conn.execute("""
            SELECT * FROM alerts
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []


def load_unresolved_alerts() -> List[Dict[str, Any]]:
    """加载未恢复告警。"""
    try:
        cur = conn.execute("""
            SELECT * FROM alerts
            WHERE resolved_at IS NULL
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []


# ── UI 组件 ────────────────────────────────────────────────────────

def _status_icon(online: bool, seconds_ago: Optional[int] = None) -> str:
    if online:
        return "🟢"
    if seconds_ago is not None and seconds_ago > 600:
        return "⚫"
    return "🔴"


def _severity_color(severity: str) -> str:
    colors = {"critical": "#dc2626", "warning": "#d97706", "info": AKO_AMBER}
    return colors.get(severity, AKO_GRAY)


def _severity_bg(severity: str) -> str:
    bgs = {"critical": "#fef2f2", "warning": "#fffbeb", "info": "#F7F3E8"}
    return bgs.get(severity, AKO_CARD)


# ═════════════════════════════════════════════════════════════════════
# 第一行：摘要指标
# ═════════════════════════════════════════════════════════════════════

agents = load_agents_status()
unresolved_alerts = load_unresolved_alerts()

online_count = sum(1 for a in agents if a.get("last_heartbeat") is not None)
total_count = len(agents)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Agent 总数", total_count)
with col2:
    st.metric("在线", f"{online_count}/{total_count}")
with col3:
    alert_count = len(unresolved_alerts)
    st.metric(
        "未恢复告警",
        alert_count,
        delta=None,
        delta_color="off" if alert_count == 0 else "inverse",
    )
with col4:
    st.metric("更新时间", datetime.now().strftime("%H:%M:%S"))

st.divider()

# ═════════════════════════════════════════════════════════════════════
# 第二行：Agent 状态表格
# ═════════════════════════════════════════════════════════════════════

st.subheader("Agent 状态")

if agents:
    df_data = []
    for a in agents:
        online = a.get("last_heartbeat") is not None
        seconds_ago = a.get("seconds_ago")
        df_data.append({
            "状态": _status_icon(online, seconds_ago),
            "Agent ID": a["agent_id"],
            "显示名": a.get("display_name", ""),
            "类型": a.get("agent_type", ""),
            "最后心跳": a.get("last_heartbeat", "N/A"),
            "间隔": f"{seconds_ago}s" if seconds_ago else "N/A",
            "CPU %": round(a.get("cpu_percent") or 0, 1),
            "内存 MB": round(a.get("memory_mb") or 0, 1),
            "任务(成/败)": f"{a.get('task_success',0)}/{a.get('task_failed',0)}",
            "最后任务": a.get("last_task", "—"),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("暂无 Agent 数据，请确保 Agent 已启动并发送心跳。")

st.divider()

# ═════════════════════════════════════════════════════════════════════
# 第三行：告警列表
# ═════════════════════════════════════════════════════════════════════

st.subheader("未恢复告警")

if unresolved_alerts:
    for alert in unresolved_alerts:
        severity = alert.get("severity", "info")
        color = _severity_color(severity)

        with st.expander(
            f"**[{severity.upper()}]** "
            f"{alert.get('agent_id', '')} — {alert.get('message', '')}"
        ):
            st.markdown(f"""
            <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">
                <div>
                    <span style="color:{AKO_AMBER};font-size:0.75rem;">告警类型</span><br>
                    <strong style="color:{AKO_DARK};">{alert.get('alert_type', '—')}</strong>
                </div>
                <div>
                    <span style="color:{AKO_AMBER};font-size:0.75rem;">创建时间</span><br>
                    <strong style="color:{AKO_DARK};">{alert.get('created_at', '—')}</strong>
                </div>
                <div>
                    <span style="color:{AKO_AMBER};font-size:0.75rem;">状态</span><br>
                    <span style="color:{color};font-weight:700;">{'已确认' if alert.get('acknowledged') else '待确认'}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_a, col_b = st.columns([1, 5])
            with col_a:
                if st.button("确认", key=f"ack_{alert['id']}", type="primary"):
                    try:
                        conn.execute(
                            "UPDATE alerts SET acknowledged = 1 WHERE id = ?",
                            (alert["id"],),
                        )
                        conn.commit()
                        st.rerun()
                    except Exception as e:
                        st.error(f"操作失败: {e}")
else:
    st.success("无未恢复告警")

# ── 自动刷新 ───────────────────────────────────────────────────────
st.sidebar.markdown(f"""
<div style="text-align:center;margin-bottom:1rem;">
    <span style="font-size:1.4rem;font-weight:800;color:{AKO_GOLD};">AKO</span>
    <span style="font-size:0.85rem;color:{AKO_AMBER};"> Hub</span>
</div>
""", unsafe_allow_html=True)

if st.sidebar.checkbox("自动刷新 (每 30 秒)", value=True):
    st.sidebar.info("页面每 30 秒自动刷新")
    import time
    time.sleep(30)
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption("AKO Hub · 心跳监控 v1.0")
