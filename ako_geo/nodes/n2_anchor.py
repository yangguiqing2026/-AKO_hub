"""
AKO Hub — ako_geo 节点 N2_Anchor
n2_anchor.py: 从 KnowledgeHub 检索知识锚点，聚合上下文。

文档编号: AGE-TECH-AKO-GEO-001 §4.3
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ako_geo.config import (
    AKO_HUB_ROOT,
    GEO_ANCHORS_COLLECTION,
    GEO_DEFAULT_COLLECTION,
    GEO_QUERY_TOP_K,
    GEO_FALLBACK_TOP_K,
)

logger = logging.getLogger("ako_geo")


def extract_anchors(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N2_Anchor: 调用 KnowledgeHub 检索知识锚点，同时读取 business_ref 关联数据。

    输入:
        state.filtered: list[dict]  — 过滤后的候选列表（取第一个处理）。
        state.current_task_id: str  — 当前处理的任务 ID。

    输出:
        state.anchors: list[dict]  — 检索到的知识锚点列表。
        state.context: str  — 聚合的上下文知识文本。
        state.current_source: dict  — 当前处理的 GeoSource 详情。

    检索策略:
        1. 优先查 hub_geo_anchors Collection（按 geo_tags 检索）。
        2. 降级到通用文档索引（按 public_abstract 检索）。
        3. 读取 business_ref 关联的商务数据文件。
    """
    logger.info("N2_Anchor: 开始提取知识锚点")

    filtered = state.get("filtered", [])
    if not filtered:
        logger.warning("N2_Anchor: 无过滤后的候选素材，跳过")
        return {**state, "anchors": [], "context": ""}

    # 取第一个候选素材（逐个处理）
    source = filtered[0]
    task_id = source.get("task_id", "unknown")
    geo_tags = source.get("geo_tags", [])
    public_abstract = source.get("public_abstract", "")
    business_ref = source.get("business_ref")

    logger.info("N2_Anchor: 处理 task_id=%s, tags=%s", task_id, geo_tags)

    # ── 1. 检索知识锚点 ─────────────────────────────────────────────
    anchors = []
    context_parts = []

    try:
        # 尝试从 Hub 获取 KnowledgeHub 实例
        # TODO: 实际部署时由 Hub 注入 knowledge_hub 实例
        knowledge_hub = _get_knowledge_hub(state)

        if knowledge_hub:
            # 优先查 hub_geo_anchors Collection
            try:
                query_text = " ".join(geo_tags) if geo_tags else public_abstract
                result = knowledge_hub.query(
                    kb_id=GEO_ANCHORS_COLLECTION,
                    query_text=query_text,
                    n_results=GEO_QUERY_TOP_K,
                )
                anchors = _parse_query_result(result)
                logger.info("N2_Anchor: 从 %s 检索到 %d 个锚点",
                            GEO_ANCHORS_COLLECTION, len(anchors))
            except Exception as e:
                logger.warning("N2_Anchor: 查询 %s 失败: %s，降级到通用索引",
                               GEO_ANCHORS_COLLECTION, e)

            # 降级到通用文档索引
            if not anchors:
                try:
                    result = knowledge_hub.query(
                        kb_id=GEO_DEFAULT_COLLECTION,
                        query_text=public_abstract,
                        n_results=GEO_FALLBACK_TOP_K,
                    )
                    anchors = _parse_query_result(result)
                    logger.info("N2_Anchor: 从通用索引检索到 %d 个锚点", len(anchors))
                except Exception as e:
                    logger.warning("N2_Anchor: 通用索引查询失败: %s", e)

    except Exception as e:
        logger.error("N2_Anchor: KnowledgeHub 不可用: %s", e)

    # 聚合上下文
    for anchor in anchors:
        context_parts.append(anchor.get("content", ""))

    # ── 2. 读取 business_ref 关联数据 ────────────────────────────────
    biz_context = ""
    if business_ref:
        biz_path = AKO_HUB_ROOT / "business_agent" / "data" / f"{business_ref}.json"
        if biz_path.exists():
            try:
                biz_data = json.loads(biz_path.read_text("utf-8"))
                biz_context = _format_biz_context(biz_data)
                logger.info("N2_Anchor: 加载商务数据: %s", business_ref)
            except Exception as e:
                logger.warning("N2_Anchor: 加载商务数据失败 %s: %s", business_ref, e)
        else:
            logger.info("N2_Anchor: 商务数据文件不存在: %s", biz_path)

    # 聚合完整上下文
    context = "\n\n".join(filter(None, [
        "## 知识锚点",
        "\n".join(context_parts) if context_parts else "（无检索结果）",
        "## 商务背景",
        biz_context,
    ]))

    logger.info("N2_Anchor: 上下文聚合完成，长度 %d 字符", len(context))

    return {
        **state,
        "anchors": anchors,
        "context": context,
        "current_source": source,
        "current_task_id": task_id,
        "current_agent": source.get("agent", ""),
    }


def _get_knowledge_hub(state: Dict[str, Any]) -> Optional[Any]:
    """
    从 state 或 Hub 全局获取 KnowledgeHub 实例。

    TODO: 实际部署时由 Hub 通过 state 注入，此处提供降级路径。
    """
    # 优先从 state 获取（Hub 注入）
    if "knowledge_hub" in state:
        return state["knowledge_hub"]

    # 降级：尝试从 Hub 全局导入
    try:
        import sys
        sys.path.insert(0, str(AKO_HUB_ROOT))
        from core.knowledge_hub import KnowledgeHub
        from core.ako_config.settings import get_settings

        settings = get_settings()
        hub = KnowledgeHub(
            db_path=str(AKO_HUB_ROOT / "hub_meta.db"),
            chroma_root=str(AKO_HUB_ROOT / "chroma_db"),
        )
        return hub
    except Exception as e:
        logger.warning("N2_Anchor: 无法初始化 KnowledgeHub: %s", e)
        return None


def _parse_query_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """解析 KnowledgeHub.query() 返回结果为锚点列表。"""
    anchors = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    scores = result.get("final_scores", result.get("similarities", [[]]))[0]

    for i, doc_id in enumerate(ids):
        anchors.append({
            "anchor_id": doc_id,
            "content": documents[i] if i < len(documents) else "",
            "score": scores[i] if i < len(scores) else 0.0,
            "metadata": metadatas[i] if i < len(metadatas) else {},
        })

    return anchors


def _format_biz_context(biz_data: Dict[str, Any]) -> str:
    """将商务数据格式化为上下文字符串。"""
    parts = []
    if "project_name" in biz_data:
        parts.append(f"项目名称: {biz_data['project_name']}")
    if "client" in biz_data:
        parts.append(f"客户: {biz_data['client']}")
    if "scope" in biz_data:
        parts.append(f"范围: {biz_data['scope']}")
    if "budget" in biz_data:
        parts.append(f"预算: {biz_data['budget']}")
    if "highlights" in biz_data:
        parts.append(f"亮点: {', '.join(biz_data['highlights'])}")

    return "\n".join(parts) if parts else json.dumps(biz_data, ensure_ascii=False, indent=2)
