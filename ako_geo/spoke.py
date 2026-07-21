"""
AKO Hub — ako_geo Spoke 适配器
spoke.py: GeoSpoke 类，继承 Hub 基类，实现 run() / register()。

文档编号: AGE-TECH-AKO-GEO-001 §6
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ako_geo.config import (
    AKO_HUB_ROOT,
    GEO_OUTPUT_ROOT,
    SCAN_INTERVAL_SECONDS,
    PLATFORMS,
)
from ako_geo.utils import setup_geo_logger, ensure_output_dirs

logger = logging.getLogger("ako_geo")


class GeoSpoke:
    """
    GEO Spoke 适配器。

    职责：
    1. 将 ako_geo LangGraph 状态机注册到 Hub。
    2. 提供 run() 接口供 Hub 调用。
    3. 管理定时扫描线程（每 15 分钟触发一次 N0_Scan）。
    4. 暴露 Gradio UI 集成接口（审核台）。

    继承关系：
        兼容 SpokeAdapter 协议（core/spoke_protocol.py）。
        复用 workflow Spoke 的 LangGraph 状态机范式。
    """

    def __init__(
        self,
        knowledge_hub: Any = None,
        llm_router: Any = None,
    ):
        """
        初始化 GeoSpoke。

        Args:
            knowledge_hub: Hub 注入的 KnowledgeHub 实例。
            llm_router: Hub 注入的 LLM 路由器实例。
        """
        self.knowledge_hub = knowledge_hub
        self.llm_router = llm_router
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_running = False
        self._compiled_graph = None

        # 初始化日志
        setup_geo_logger()

        # 确保输出目录存在
        ensure_output_dirs()

        logger.info("GeoSpoke: 初始化完成")

    def run(
        self,
        intent: str = "",
        project_tag: str = "",
        _hub_output_dir: str = "",
        _hub_db_path: str = "",
        _hub_chroma_root: str = "",
        _hub_file_root: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        SpokeAdapter 协议入口：执行一次完整的 GEO 流程。

        Args:
            intent: 任务意图（此处用于指定 task_id 或平台）。
            project_tag: 项目标签。
            _hub_output_dir: Hub 下发的产出目录。
            _hub_db_path: Hub 元数据库路径。
            _hub_chroma_root: ChromaDB 根目录。
            _hub_file_root: 文件总线根目录。
            **kwargs: 额外参数，支持:
                - sources: list[str]  — 手动指定 geo.yaml 路径。
                - platform: str  — 目标平台（默认 zhihu）。
                - thread_id: str  — LangGraph thread ID（用于 resume）。

        Returns:
            {
                "output_files": List[str],
                "summary": str,
                "error": Optional[str],
            }
        """
        logger.info("GeoSpoke.run: intent=%s, project=%s", intent, project_tag)

        sources = kwargs.get("sources", [])
        platform = kwargs.get("platform", "zhihu")
        thread_id = kwargs.get("thread_id", "")

        if platform not in PLATFORMS:
            return {
                "output_files": [],
                "summary": f"不支持的平台: {platform}",
                "error": f"非法平台: {platform}，可选: {PLATFORMS}",
            }

        try:
            # 导入并编译状态图
            from ako_geo.graph import build_geo_graph, create_initial_state

            compiled = build_geo_graph()

            # 创建初始状态
            initial_state = create_initial_state(
                sources=sources,
                platform=platform,
                knowledge_hub=self.knowledge_hub,
                llm_router=self.llm_router,
            )

            # 执行状态图
            config = {"configurable": {"thread_id": thread_id or f"geo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"}}
            result = compiled.invoke(initial_state, config=config)

            # 提取输出文件
            file_paths = result.get("file_paths", [])
            output_files = [str(p) for p in file_paths]

            # 生成摘要
            task_id = result.get("current_task_id", "unknown")
            status = result.get("review_status", "unknown")
            summary = f"GEO 流程完成: task_id={task_id}, platform={platform}, status={status}, files={len(output_files)}"

            error = result.get("error_message")

            return {
                "output_files": output_files,
                "summary": summary,
                "error": error,
            }

        except Exception as e:
            logger.error("GeoSpoke.run: 执行失败: %s", e, exc_info=True)
            return {
                "output_files": [],
                "summary": f"GEO 流程异常: {type(e).__name__}",
                "error": str(e),
            }

    def register(self) -> Dict[str, Any]:
        """
        注册到 Hub 注册表。

        Returns:
            SpokeInfo 字典（兼容 registry/workflows.py 格式）。
        """
        return {
            "workflow_id": "AKO_geo",
            "name": "AKO_geo",
            "spoke_type": "workflow",
            "entry_module": "ako_geo.spoke",
            "entry_function": "run",
            "required_kb_ids": ["hub_geo_anchors", "ako_taoli_general_arch"],
            "output_dir": "geo_output",
            "description": "内容营销×GEO×知识发酵：将业务成果外化为多平台营销内容",
            "status": "registered",
            "source_dir": str(AKO_HUB_ROOT / "ako_geo"),
        }

    # ── 定时扫描管理 ──────────────────────────────────────────────────

    def start_scan_scheduler(self) -> None:
        """启动定时扫描线程（每 SCAN_INTERVAL_SECONDS 秒触发一次）。"""
        if self._scan_running:
            logger.warning("GeoSpoke: 扫描调度器已在运行")
            return

        self._scan_running = True
        self._scan_thread = threading.Thread(
            target=self._scan_loop,
            name="ako_geo_scan",
            daemon=True,
        )
        self._scan_thread.start()
        logger.info("GeoSpoke: 扫描调度器已启动，间隔 %d 秒", SCAN_INTERVAL_SECONDS)

    def stop_scan_scheduler(self) -> None:
        """停止定时扫描。"""
        self._scan_running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
        logger.info("GeoSpoke: 扫描调度器已停止")

    def _scan_loop(self) -> None:
        """定时扫描循环。"""
        while self._scan_running:
            try:
                logger.info("GeoSpoke: 触发定时扫描")
                result = self.run(intent="scan", platform="zhihu")
                logger.info("GeoSpoke: 扫描结果: %s", result.get("summary"))
            except Exception as e:
                logger.error("GeoSpoke: 扫描异常: %s", e)

            # 等待下一次扫描
            for _ in range(SCAN_INTERVAL_SECONDS):
                if not self._scan_running:
                    break
                time.sleep(1)

    # ── Gradio UI 集成接口 ────────────────────────────────────────────

    def get_pending_reviews(self) -> List[Dict[str, Any]]:
        """
        获取待审核的大纲列表（供 Gradio GEO 审核台使用）。

        Returns:
            待审核任务列表，每项包含:
                - thread_id: str
                - task_id: str
                - agent: str
                - platform: str
                - outline: str
        """
        # TODO: 从 LangGraph checkpoint 中读取 pending 状态
        # 实际实现需要查询 checkpointer 中 _waiting_review=True 的 thread
        logger.info("GeoSpoke: 获取待审核列表")
        return []

    def submit_review(
        self,
        thread_id: str,
        status: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        提交审核结果（由 Gradio GEO 审核台调用）。

        Args:
            thread_id: LangGraph thread ID。
            status: 审核状态（approved/rejected/revised）。
            comment: 审核意见。

        Returns:
            恢复执行后的结果。
        """
        logger.info("GeoSpoke: 提交审核 thread=%s, status=%s", thread_id, status)

        from ako_geo.graph import resume_with_review, compiled_graph

        if compiled_graph is None:
            return {"error": "状态图未编译"}

        # 恢复执行
        result = resume_with_review(
            thread_id=thread_id,
            review_status=status,
            review_comment=comment,
            checkpointer=compiled_graph.checkpointer,
        )

        return result


# ── 模块级 run() 函数（兼容 SpokeAdapter 协议）───────────────────────

_instance: Optional[GeoSpoke] = None


def run(**kwargs) -> Dict[str, Any]:
    """
    模块级 run() 函数，兼容 SpokeAdapter 协议。

    Hub 的 workflow_caller 通过 importlib 动态导入后调用此函数。
    """
    global _instance
    if _instance is None:
        _instance = GeoSpoke()
    return _instance.run(**kwargs)
