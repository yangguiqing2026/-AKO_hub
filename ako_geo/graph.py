"""
AKO Hub — ako_geo LangGraph 状态机
graph.py: 定义 GEO Spoke 的 9 节点状态图。

文档编号: AGE-TECH-AKO-GEO-001 §5

状态转移:
    N0_Scan ──► N1_Filter ──► N2_Anchor ──► N3_Outline
                                                  │
                                                  ▼
    N8_Ferment ◄── N7_Store ◄── N6_Publish ◄── N5_Format ◄── N4_Review
                                                  ▲
                                                  │
                                                  └── (approved)
                                                  │
                                                  └── (rejected/revised) ──► N3_Outline (循环，max 3)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ako_geo.nodes import (
    scan_sources,
    filter_candidates,
    extract_anchors,
    generate_outline,
    human_review,
    should_continue_to_format,
    format_platform,
    prepare_publish,
    store_output,
    ferment_knowledge,
)
from ako_geo.config import MAX_REVIEW_LOOP, PLATFORMS

logger = logging.getLogger("ako_geo")


# ── State 定义 ────────────────────────────────────────────────────────

class GeoGraphState(TypedDict, total=False):
    """
    LangGraph 状态定义。

    贯穿 N0_Scan → N8_Ferment 全流程。
    """
    # N0_Scan
    sources: List[str]
    candidates: List[Dict[str, Any]]
    processed_task_ids: List[str]

    # N1_Filter
    filtered: List[Dict[str, Any]]

    # N2_Anchor
    anchors: List[Dict[str, Any]]
    context: str
    current_source: Dict[str, Any]
    current_task_id: str
    current_agent: str

    # N3_Outline
    outline: str

    # N4_Review
    review_status: str
    review_comment: Optional[str]
    review_loop_count: int
    _waiting_review: bool
    _review_result: Optional[Dict[str, Any]]

    # N5_Format
    content: str
    current_platform: str

    # N6_Publish
    publish_pack: Optional[Dict[str, Any]]

    # N7_Store
    file_paths: List[str]

    # N8_Ferment
    new_anchors: List[Dict[str, Any]]
    ferment_result: Optional[Dict[str, Any]]

    # 全局
    error_message: Optional[str]

    # Hub 注入
    knowledge_hub: Any
    llm_router: Any


# ── 失败处理节点 ──────────────────────────────────────────────────────

def handle_failed(state: GeoGraphState) -> Dict[str, Any]:
    """
    失败处理节点：审核超过最大循环次数或生成失败时的兜底。

    将状态标记为 failed，写入 failed/ 目录（由 N7_Store 处理）。
    """
    logger.warning("GEO Graph: 进入失败处理，task_id=%s", state.get("current_task_id"))
    return {
        **state,
        "review_status": "failed",
        "error_message": state.get("error_message", "审核失败或生成失败"),
    }


# ── 条件路由函数 ──────────────────────────────────────────────────────

def route_after_review(state: GeoGraphState) -> str:
    """
    N4_Review 后的条件路由。

    Returns:
        "format"  → 审核通过，继续 N5_Format
        "outline" → 审核驳回/修改，回到 N3_Outline
        "failed"  → 超过循环上限，进入失败处理
        "wait"    → 等待审核（interrupt 挂起）
    """
    status = state.get("review_status", "pending")
    waiting = state.get("_waiting_review", False)

    if waiting:
        return "wait"

    if status == "approved":
        return "format"
    elif status in ("rejected", "revised"):
        loop_count = state.get("review_loop_count", 0)
        if loop_count >= MAX_REVIEW_LOOP:
            return "failed"
        return "outline"
    elif status == "failed":
        return "failed"
    else:
        return "wait"


def route_after_filter(state: GeoGraphState) -> str:
    """
    N1_Filter 后的条件路由：无候选素材时直接结束。
    """
    filtered = state.get("filtered", [])
    if not filtered:
        logger.info("GEO Graph: 无有效候选，流程结束")
        return "end"
    return "anchor"


# ── 构建状态图 ────────────────────────────────────────────────────────

def build_geo_graph() -> StateGraph:
    """
    构建 GEO Spoke 的 LangGraph 状态图。

    Returns:
        编译后的 StateGraph 对象。
    """
    # 创建状态图
    workflow = StateGraph(GeoGraphState)

    # ── 添加节点 ──────────────────────────────────────────────────────
    workflow.add_node("N0_Scan", scan_sources)
    workflow.add_node("N1_Filter", filter_candidates)
    workflow.add_node("N2_Anchor", extract_anchors)
    workflow.add_node("N3_Outline", generate_outline)
    workflow.add_node("N4_Review", human_review)
    workflow.add_node("N5_Format", format_platform)
    workflow.add_node("N6_Publish", prepare_publish)
    workflow.add_node("N7_Store", store_output)
    workflow.add_node("N8_Ferment", ferment_knowledge)
    workflow.add_node("handle_failed", handle_failed)

    # ── 设置入口 ──────────────────────────────────────────────────────
    workflow.set_entry_point("N0_Scan")

    # ── 添加边 ────────────────────────────────────────────────────────
    # N0_Scan → N1_Filter
    workflow.add_edge("N0_Scan", "N1_Filter")

    # N1_Filter → (条件) → N2_Anchor 或 END
    workflow.add_conditional_edges(
        "N1_Filter",
        route_after_filter,
        {
            "anchor": "N2_Anchor",
            "end": END,
        },
    )

    # N2_Anchor → N3_Outline
    workflow.add_edge("N2_Anchor", "N3_Outline")

    # N3_Outline → N4_Review
    workflow.add_edge("N3_Outline", "N4_Review")

    # N4_Review → (条件) → N5_Format / N3_Outline / handle_failed / wait
    workflow.add_conditional_edges(
        "N4_Review",
        route_after_review,
        {
            "format": "N5_Format",
            "outline": "N3_Outline",
            "failed": "handle_failed",
            "wait": END,  # interrupt 挂起，等待 resume
        },
    )

    # N5_Format → N6_Publish
    workflow.add_edge("N5_Format", "N6_Publish")

    # N6_Publish → N7_Store
    workflow.add_edge("N6_Publish", "N7_Store")

    # N7_Store → N8_Ferment
    workflow.add_edge("N7_Store", "N8_Ferment")

    # N8_Ferment → END
    workflow.add_edge("N8_Ferment", END)

    # handle_failed → N7_Store（写入 failed/ 目录）→ END
    workflow.add_edge("handle_failed", "N7_Store")

    # ── 编译（带 checkpoint 以支持 interrupt/resume）─────────────────
    memory = MemorySaver()
    compiled = workflow.compile(
        checkpointer=memory,
        interrupt_before=["N4_Review"],  # N4_Review 前中断，等待人工审核
    )

    logger.info("GEO Graph: 状态图编译完成")
    return compiled


# ── 便捷函数 ──────────────────────────────────────────────────────────

def create_initial_state(
    sources: Optional[List[str]] = None,
    platform: str = "zhihu",
    knowledge_hub: Any = None,
    llm_router: Any = None,
) -> GeoGraphState:
    """
    创建初始状态。

    Args:
        sources: 手动指定的 geo.yaml 路径列表（为 None 时自动扫描）。
        platform: 目标平台。
        knowledge_hub: Hub 注入的 KnowledgeHub 实例。
        llm_router: Hub 注入的 LLM 路由器实例。

    Returns:
        初始状态字典。
    """
    return GeoGraphState(
        sources=sources or [],
        candidates=[],
        processed_task_ids=[],
        filtered=[],
        anchors=[],
        context="",
        current_source={},
        current_task_id="",
        current_agent="",
        outline="",
        review_status="pending",
        review_comment=None,
        review_loop_count=0,
        _waiting_review=False,
        _review_result=None,
        content="",
        current_platform=platform,
        publish_pack=None,
        file_paths=[],
        new_anchors=[],
        ferment_result=None,
        error_message=None,
        knowledge_hub=knowledge_hub,
        llm_router=llm_router,
    )


def resume_with_review(
    thread_id: str,
    review_status: str,
    review_comment: Optional[str] = None,
    checkpointer: Any = None,
) -> Dict[str, Any]:
    """
    恢复审核后的执行（由 Gradio UI 调用）。

    Args:
        thread_id: LangGraph thread ID。
        review_status: 审核状态（approved/rejected/revised）。
        review_comment: 审核意见。
        checkpointer: LangGraph checkpointer 实例。

    Returns:
        恢复执行后的最终状态。
    """
    if checkpointer is None:
        logger.error("resume_with_review: 无 checkpointer，无法恢复")
        return {}

    # 构建 resume 输入
    resume_input = {
        "_review_result": {
            "status": review_status,
            "comment": review_comment,
        },
    }

    # 通过 Command("resume") 恢复执行
    # TODO: 实际实现需要对接 LangGraph 的 Command API
    # from langgraph.types import Command
    # result = compiled.invoke(Command(resume=resume_input), config={"configurable": {"thread_id": thread_id}})

    logger.info("resume_with_review: thread=%s, status=%s", thread_id, review_status)
    return resume_input


# ── 编译图对象（供 spoke.py 导入）─────────────────────────────────────

try:
    compiled_graph = build_geo_graph()
except Exception as e:
    logger.error("GEO Graph: 编译失败: %s", e)
    compiled_graph = None
