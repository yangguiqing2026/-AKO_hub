"""
AKO Hub — Master Graph 构建
graph.py: 用 LangGraph 编排主控状态机。

文档编号: AGE-TECH-AKO-HUB-001 §6

节点链路：
  task_router → kb_allocator → workflow_caller → file_collector → state_aggregator → sync_monitor → END
                    ↓              ↓
              error_handler ← error_handler
                    ↓ (重试)           ↓ (最终失败)
              workflow_caller        END

使用：
    from master.graph import master_graph
    result = master_graph.invoke({
        "task_id": "T-001",
        "input_payload": {"intent": "结构计算", "project": "陶粒墙板"},
    })
"""

from typing import Literal

from langgraph.graph import StateGraph, END

from master.state import MasterState
from master.nodes import (
    task_router,
    kb_allocator,
    workflow_caller,
    file_collector,
    error_handler,
    state_aggregator,
    sync_monitor,
)


# ── 条件路由函数 ──────────────────────────────────────────────────

def _route_after_router(state: MasterState) -> Literal["kb_allocator", "error_handler"]:
    if state.get("status") == "failed":
        return "error_handler"
    return "kb_allocator"


def _route_after_kb(state: MasterState) -> Literal["workflow_caller", "error_handler"]:
    if state.get("status") == "failed" or state.get("kb_status") != "ok":
        return "error_handler"
    return "workflow_caller"


def _route_after_caller(state: MasterState) -> Literal["file_collector", "error_handler"]:
    if state.get("status") == "failed":
        return "error_handler"
    return "file_collector"


def _route_after_collector(state: MasterState) -> Literal["state_aggregator", "error_handler"]:
    # 即使没注册到文件，也走 aggregator 完成
    if state.get("status") == "failed":
        return "error_handler"
    return "state_aggregator"


def _route_after_error(state: MasterState) -> Literal["workflow_caller", "__end__"]:
    """
    错误处理后的路由：
      - status="running" 表示可重试 → 回到 workflow_caller
      - status="failed" 表示最终失败 → END
    """
    if state.get("status") == "running":
        return "workflow_caller"
    return "__end__"


# ── 构建 Master Graph ───────────────────────────────────────────

def build_master_graph() -> StateGraph:
    builder = StateGraph(MasterState)

    # 注册节点
    builder.add_node("task_router", task_router)
    builder.add_node("kb_allocator", kb_allocator)
    builder.add_node("workflow_caller", workflow_caller)
    builder.add_node("file_collector", file_collector)
    builder.add_node("state_aggregator", state_aggregator)
    builder.add_node("error_handler", error_handler)
    builder.add_node("sync_monitor", sync_monitor)

    # 入口
    builder.set_entry_point("task_router")

    # 边
    builder.add_conditional_edges(
        "task_router",
        _route_after_router,
        {"kb_allocator": "kb_allocator", "error_handler": "error_handler"},
    )
    builder.add_conditional_edges(
        "kb_allocator",
        _route_after_kb,
        {"workflow_caller": "workflow_caller", "error_handler": "error_handler"},
    )
    builder.add_conditional_edges(
        "workflow_caller",
        _route_after_caller,
        {"file_collector": "file_collector", "error_handler": "error_handler"},
    )
    builder.add_conditional_edges(
        "file_collector",
        _route_after_collector,
        {"state_aggregator": "state_aggregator", "error_handler": "error_handler"},
    )

    # error_handler 条件边：重试 → workflow_caller，终止 → END
    builder.add_conditional_edges(
        "error_handler",
        _route_after_error,
        {"workflow_caller": "workflow_caller", "__end__": END},
    )

    # 终结：state_aggregator → sync_monitor → END
    builder.add_edge("state_aggregator", "sync_monitor")
    builder.add_edge("sync_monitor", END)

    return builder.compile()


# ── 全局单例（按需导入） ──────────────────────────────────────────
_master_graph_instance = None

def get_master_graph():
    global _master_graph_instance
    if _master_graph_instance is None:
        _master_graph_instance = build_master_graph()
    return _master_graph_instance


# 直接导出，方便 import
master_graph = get_master_graph()
