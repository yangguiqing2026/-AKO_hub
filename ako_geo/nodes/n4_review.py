"""
AKO Hub — ako_geo 节点 N4_Review
n4_review.py: 人工审核节点，通过 LangGraph interrupt 实现。

文档编号: AGE-TECH-AKO-GEO-001 §4.5
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ako_geo.config import MAX_REVIEW_LOOP

logger = logging.getLogger("ako_geo")


def human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N4_Review: 人工审核节点。

    输入:
        state.outline: str  — 待审核的大纲。
        state.current_task_id: str  — 当前任务 ID。
        state.current_agent: str  — 来源 Agent。
        state.current_platform: str  — 目标平台。
        state.review_loop_count: int  — 当前审核循环次数。

    输出:
        state.review_status: str  — 审核状态（approved/rejected/revised/failed）。
        state.review_comment: str?  — 审核意见。
        state.review_loop_count: int  — 更新后的循环次数。

    实现方式:
        通过 LangGraph 的 interrupt() 机制暂停执行，
        等待 Gradio UI（GEO 审核台）提交审核结果后恢复。

    审核循环:
        - approved: 继续到 N5_Format。
        - rejected/revised: 回到 N3_Outline 重新生成（最多 MAX_REVIEW_LOOP 次）。
        - 超过 MAX_REVIEW_LOOP: 标记 failed，写入 failed/ 目录。
    """
    logger.info("N4_Review: 等待人工审核 task_id=%s", state.get("current_task_id"))

    outline = state.get("outline", "")
    if not outline:
        logger.error("N4_Review: 无大纲可审核")
        return {
            **state,
            "review_status": "failed",
            "review_comment": "无大纲内容",
        }

    # 检查审核循环次数
    loop_count = state.get("review_loop_count", 0)
    if loop_count >= MAX_REVIEW_LOOP:
        logger.warning("N4_Review: 审核循环超过 %d 次，标记为 failed", MAX_REVIEW_LOOP)
        return {
            **state,
            "review_status": "failed",
            "review_comment": f"审核循环超过 {MAX_REVIEW_LOOP} 次上限",
            "review_loop_count": loop_count,
        }

    # ── LangGraph interrupt 实现 ──────────────────────────────────────
    # 在实际 LangGraph 图中，此处会调用 interrupt() 暂停执行。
    # Gradio UI 渲染审核面板，用户提交后通过 Command("resume") 恢复。
    #
    # 此处检查 state 中是否已有审核结果（由 resume 注入）
    review_result = state.get("_review_result")

    if review_result is None:
        # 首次进入，触发 interrupt（在 graph.py 中配置）
        # 返回当前状态，等待 UI 提交
        logger.info("N4_Review: 触发 interrupt，等待审核")
        return {
            **state,
            "_waiting_review": True,
            "review_status": "pending",
        }

    # 处理审核结果
    status = review_result.get("status", "pending")
    comment = review_result.get("comment", "")

    logger.info("N4_Review: 收到审核结果: status=%s, comment=%s", status, comment)

    new_loop_count = loop_count + 1 if status in ("rejected", "revised") else loop_count

    return {
        **state,
        "review_status": status,
        "review_comment": comment,
        "review_loop_count": new_loop_count,
        "_waiting_review": False,
        "_review_result": None,  # 清除，避免下次循环使用旧结果
    }


def should_continue_to_format(state: Dict[str, Any]) -> str:
    """
    条件边函数：根据审核状态决定下一步走向。

    Returns:
        "format"  → 审核通过，继续 N5_Format。
        "outline" → 审核驳回/修改，回到 N3_Outline。
        "failed"  → 超过循环上限，进入失败处理。
    """
    status = state.get("review_status", "pending")

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
        # pending 或未知状态，等待审核
        return "wait"
