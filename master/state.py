"""
AKO Hub — Master Graph 状态定义
MasterState: 主控编排器的全局状态类型。

文档编号: AGE-TECH-AKO-HUB-001 §6.1
"""

from typing import TypedDict, List, Optional, Dict, Any


class MasterState(TypedDict):
    """
    Master Graph 全局状态。

    生命周期：
        pending → running → (done | failed | cancelled)
    """

    # ── 任务标识 ───────────────────────────────────────────────
    task_id: str                          # 全局唯一，如 "T-20260615-001"
    target_workflow: str                  # 目标工作流 ID，如 "wf_ako_image_analyzer"
    target_agent: Optional[str]           # 目标 Agent（如 workflow 内嵌 agent）

    # ── 输入 ───────────────────────────────────────────────────
    input_payload: Dict[str, Any]         # 输入参数，JSON 可序列化字典
    required_kb_ids: List[str]            # 需挂载的知识库 kb_id 列表
    output_dir: Optional[str]             # 输出目录约束（相对于 files/ 的 rel_path）

    # ── 输出 ───────────────────────────────────────────────────
    generated_files: List[str]            # 产出 file_id 列表（由 file_collector 填充）
    output_summary: Optional[str]         # 产出摘要

    # ── 状态机 ─────────────────────────────────────────────────
    status: str                           # pending / running / done / failed / cancelled
    error_log: Optional[str]              # 错误信息（失败时填充）
    retry_count: int                      # 当前重试次数
    max_retry: int                        # 最大重试次数（默认 3）

    # ── 时间戳 ─────────────────────────────────────────────────
    started_at: Optional[str]             # ISO 8601
    finished_at: Optional[str]            # ISO 8601

    # ── 内部标记（可选） ───────────────────────────────────────
    kb_status: Optional[str]              # kb_allocator 节点填充：ok / missing / forbidden
    sync_status: Optional[str]           # sync_monitor 节点填充：ok / mismatch / partial
    spoke_output_paths: List[str]        # workflow_caller 从 Spoke 返回的原始路径列表
