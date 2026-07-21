"""
02_日志中心.py — Streamlit 页面：AKO 系统日志中心。

支持按 Agent / 级别 / 时间范围筛选日志，全文搜索。
文档编号: AGE-TECH-AKO-HUB-020 §LogCenter
"""

import sqlite3
import sys
from datetime import datetime, timedelta
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
    page_title="日志中心 — AKO Hub",
    page_icon="📋",
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

    /* ── Select/Slider 标签 ── */
    .stSelectbox label, .stSlider label, .stTextInput label {{
        color: {AKO_GOLD} !important;
        font-weight: 600;
        font-size: 0.8rem;
    }}

    /* ── 分割线 ── */
    hr {{
        border-color: {AKO_GRAY}66;
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
    [data-testid="stDataFrame"] tr:nth-child(even) {{
        background-color: {AKO_CARD};
    }}

    /* ── 侧边栏 ── */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {AKO_CARD} 0%, {AKO_CREAM} 100%);
        border-right: 1px solid {AKO_GRAY}66;
    }}
    [data-testid="stSidebar"] .st-caption {{
        color: {AKO_AMBER} !important;
    }}

    /* ── JSON 展开区 ── */
    [data-testid="stJson"] {{
        border: 1px solid {AKO_GRAY}66;
        border-radius: 8px;
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

    /* ── info 容器 ── */
    [data-testid="stInfo"] {{
        background: {AKO_CARD};
    }}

    /* ── 输入框 ── */
    input, textarea, .stTextInput input {{
        border-color: {AKO_GRAY} !important;
    }}
    input:focus, textarea:focus {{
        border-color: {AKO_GOLD} !important;
        box-shadow: 0 0 0 1px {AKO_GOLD}44 !important;
    }}
</style>
""", unsafe_allow_html=True)


st.title("日志中心")
st.caption("Agent 日志检索 · 全文搜索")


# ── 数据库连接 ─────────────────────────────────────────────────────
@st.cache_resource(ttl=10)
def _get_conn():
    db_path = PROJECT_ROOT / "ako_hub.db"
    conn = sqlite3.connect(str(db_path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


conn = _get_conn()


# ── 筛选控件 ───────────────────────────────────────────────────────

def _get_agent_list() -> List[str]:
    try:
        cur = conn.execute("SELECT DISTINCT agent_id FROM logs ORDER BY agent_id")
        return [row["agent_id"] for row in cur.fetchall()]
    except Exception:
        return []


agent_list = _get_agent_list()

with st.container():
    st.markdown("### 筛选条件")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        selected_agent = st.selectbox("Agent", ["全部"] + agent_list, index=0)
    with col2:
        selected_level = st.selectbox("日志级别", ["全部", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"])
    with col3:
        time_range = st.selectbox(
            "时间范围",
            ["最近 1 小时", "最近 6 小时", "最近 24 小时", "最近 3 天", "最近 7 天", "全部"],
            index=2,
        )
    with col4:
        search_text = st.text_input("全文搜索", placeholder="输入关键词...")

    limit = st.slider("显示条数", 20, 500, 100, step=20)

st.divider()

# ── 查询构建 ───────────────────────────────────────────────────────

_time_deltas = {
    "最近 1 小时": timedelta(hours=1),
    "最近 6 小时": timedelta(hours=6),
    "最近 24 小时": timedelta(hours=24),
    "最近 3 天": timedelta(days=3),
    "最近 7 天": timedelta(days=7),
}

# 日志级别配色（功能性，非品牌色）
LEVEL_COLORS = {
    "DEBUG": "#94a3b8",
    "INFO":  "#6b8a9e",
    "WARN":  "#d97706",
    "ERROR": "#dc2626",
    "FATAL": "#991b1b",
}
LEVEL_BG = {
    "DEBUG": "#f1f3f4",
    "INFO":  "#eef2f5",
    "WARN":  "#fffbeb",
    "ERROR": "#fef2f2",
    "FATAL": "#fef2f2",
}


def _query_logs() -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: List[Any] = []

    if selected_agent != "全部":
        conditions.append("l.agent_id = ?")
        params.append(selected_agent)

    if selected_level != "全部":
        conditions.append("l.level = ?")
        params.append(selected_level)

    if time_range in _time_deltas:
        since = (datetime.now() - _time_deltas[time_range]).isoformat()
        conditions.append("l.timestamp >= ?")
        params.append(since)

    if search_text.strip():
        conditions.append("l.message LIKE ?")
        params.append(f"%{search_text.strip()}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    try:
        cur = conn.execute(
            f"""
            SELECT l.*, a.display_name
            FROM logs l
            LEFT JOIN agents_registry a ON l.agent_id = a.agent_id
            WHERE {where_clause}
            ORDER BY l.timestamp DESC
            LIMIT ?
            """,
            params + [limit],
        )
        return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        st.error(f"查询失败: {e}")
        return []


# ═════════════════════════════════════════════════════════════════════
# 日志表格
# ═════════════════════════════════════════════════════════════════════

logs = _query_logs()

st.subheader(f"查询结果 ({len(logs)} 条)")

if logs:
    df_data = []
    for log in logs:
        level = log.get("level", "INFO")
        df_data.append({
            "时间": log.get("timestamp", ""),
            "级别": level,
            "Agent": log.get("agent_id", ""),
            "消息": log.get("message", ""),
            "TraceID": log.get("trace_id", "—"),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 日志详情 ─────────────────────────────────────────────────
    st.divider()
    st.subheader("日志详情")

    selected_row = st.number_input(
        "选中行号查看详情 (0 = 不展开)",
        min_value=0,
        max_value=len(logs),
        value=0,
    )

    if selected_row > 0 and selected_row <= len(logs):
        log = logs[selected_row - 1]
        level = log.get("level", "INFO")
        lc = LEVEL_COLORS.get(level, AKO_GRAY)
        lb = LEVEL_BG.get(level, AKO_CARD)

        st.markdown(f"""
        <div style="background:{lb};border-left:4px solid {AKO_GOLD};border-radius:8px;padding:1rem 1.5rem;margin-bottom:1rem;">
            <span style="display:inline-block;background:{lc};color:#fff;padding:2px 12px;border-radius:12px;font-size:0.72rem;font-weight:700;">{level}</span>
            <strong style="margin-left:0.75rem;color:{AKO_GOLD};">{log.get('agent_id', '—')}</strong>
            <span style="color:{AKO_AMBER};margin-left:0.5rem;">{log.get('timestamp', '')}</span>
            <p style="margin-top:0.6rem;color:{AKO_DARK};">{log.get('message', '')}</p>
        </div>
        """, unsafe_allow_html=True)

        st.json({
            "id": log.get("id"),
            "trace_id": log.get("trace_id"),
            "agent_id": log.get("agent_id"),
            "level": level,
            "message": log.get("message"),
            "context": log.get("context"),
            "timestamp": log.get("timestamp"),
        })
else:
    st.info("暂无匹配日志")


# ── 日志统计 ───────────────────────────────────────────────────────

st.sidebar.markdown(f"""
<div style="text-align:center;margin-bottom:1rem;">
    <span style="font-size:1.4rem;font-weight:800;color:{AKO_GOLD};">AKO</span>
    <span style="font-size:0.85rem;color:{AKO_AMBER};"> Hub</span>
</div>
""", unsafe_allow_html=True)

st.sidebar.subheader("日志统计 (当前筛选)")

try:
    if selected_agent != "全部":
        stat_cur = conn.execute(
            "SELECT level, COUNT(*) AS cnt FROM logs WHERE agent_id = ? GROUP BY level",
            (selected_agent,),
        )
    else:
        stat_cur = conn.execute("SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level")

    stats = list(stat_cur.fetchall())
    if stats:
        for row in stats:
            level = row["level"]
            cnt = row["cnt"]
            lc = LEVEL_COLORS.get(level, AKO_GRAY)
            st.sidebar.markdown(
                f'<span style="display:inline-block;background:{lc};color:#fff;'
                f'padding:2px 10px;border-radius:10px;font-size:0.7rem;font-weight:700;">'
                f'{level}</span> '
                f'<strong style="color:{AKO_GOLD};">{cnt}</strong> 条',
                unsafe_allow_html=True,
            )
    else:
        st.sidebar.caption("无数据")
except Exception:
    st.sidebar.caption("统计不可用")

st.sidebar.markdown("---")
st.sidebar.caption("AKO Hub · 日志中心 v1.0")
