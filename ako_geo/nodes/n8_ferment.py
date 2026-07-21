"""
AKO Hub — ako_geo 节点 N8_Ferment
n8_ferment.py: 知识发酵 — 将生成的内容回写知识库，标记知识缺口。

文档编号: AGE-TECH-AKO-GEO-001 §4.9
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ako_geo.config import GEO_OUTPUT_ROOT, GEO_ANCHORS_COLLECTION
from ako_geo.utils import get_month_dir

logger = logging.getLogger("ako_geo")


def ferment_knowledge(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N8_Ferment: 知识发酵 — 将内容中的新断言回写知识库，标记知识缺口。

    输入:
        state.content: str  — 生成的正文内容。
        state.anchors: list[dict]  — 使用的知识锚点。
        state.current_source: dict  — 当前素材详情。
        state.current_task_id: str  — 任务 ID。
        state.file_paths: list[Path]  — 生成的文件路径。

    输出:
        state.new_anchors: list[dict]  — 新回写的锚点列表。
        state.ferment_result: dict  — 发酵结果（含 gaps、obsidian_note_path）。

    发酵策略:
        1. 从 content 中提取新的断言（key_claims 中的量化值）。
        2. 回写到 hub_geo_anchors Collection。
        3. 标记内容中涉及但知识库缺失的领域为 gap。
        4. 生成 Obsidian 笔记到 geo_output/obsidian/YYYY-MM/。
    """
    logger.info("N8_Ferment: 开始知识发酵")

    content = state.get("content", "")
    anchors = state.get("anchors", [])
    source = state.get("current_source", {})
    task_id = state.get("current_task_id", "unknown")

    if not content:
        logger.warning("N8_Ferment: 无正文内容，跳过发酵")
        return {**state, "new_anchors": []}

    # ── 1. 提取新断言 ─────────────────────────────────────────────────
    new_claims = _extract_new_claims(content, source)
    logger.info("N8_Ferment: 提取到 %d 条新断言", len(new_claims))

    # ── 2. 回写知识库 ─────────────────────────────────────────────────
    new_anchors = []
    try:
        knowledge_hub = _get_knowledge_hub(state)
        if knowledge_hub and new_claims:
            anchor_ids = []
            anchor_docs = []
            anchor_metas = []

            for i, claim in enumerate(new_claims):
                anchor_id = f"geo_{task_id}_{i}"
                anchor_ids.append(anchor_id)
                anchor_docs.append(claim["text"])
                anchor_metas.append({
                    "source_task_id": task_id,
                    "source_agent": source.get("agent", ""),
                    "created_at": datetime.now().isoformat(),
                    "confidence": "P1",  # 新断言默认 P1
                    "geo_tags": json.dumps(source.get("geo_tags", []), ensure_ascii=False),
                })

            # 批量写入
            knowledge_hub.upsert(
                kb_id=GEO_ANCHORS_COLLECTION,
                ids=anchor_ids,
                documents=anchor_docs,
                metadatas=anchor_metas,
            )

            new_anchors = [
                {"anchor_id": aid, "content": doc, "metadata": meta}
                for aid, doc, meta in zip(anchor_ids, anchor_docs, anchor_metas)
            ]
            logger.info("N8_Ferment: 回写 %d 个锚点到 %s", len(new_anchors), GEO_ANCHORS_COLLECTION)

    except Exception as e:
        logger.error("N8_Ferment: 回写知识库失败: %s", e)

    # ── 3. 标记知识缺口 ───────────────────────────────────────────────
    gaps = _identify_gaps(content, anchors, source)
    if gaps:
        logger.info("N8_Ferment: 标记 %d 个知识缺口", len(gaps))
        # TODO: 将 gaps 写入 hub_geo_gaps Collection 或文件

    # ── 4. 生成 Obsidian 笔记 ─────────────────────────────────────────
    obsidian_path = _generate_obsidian_note(state, content, new_anchors, gaps)

    ferment_result = {
        "new_anchors_count": len(new_anchors),
        "gaps_count": len(gaps),
        "gaps": gaps,
        "obsidian_note_path": str(obsidian_path) if obsidian_path else None,
    }

    logger.info("N8_Ferment: 知识发酵完成")

    return {
        **state,
        "new_anchors": new_anchors,
        "ferment_result": ferment_result,
    }


def _extract_new_claims(content: str, source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从内容和素材中提取新断言。"""
    claims = []

    # 从 source 的 key_claims 提取
    source_claims = source.get("key_claims", [])
    for claim_text in source_claims:
        claims.append({
            "text": claim_text,
            "source": "geo.yaml",
        })

    # TODO: 从 content 中用 LLM 提取额外断言（需要 Nomic/LLM 支持）

    return claims


def _identify_gaps(
    content: str,
    anchors: List[Dict[str, Any]],
    source: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    识别知识缺口：内容中涉及但知识库锚点未覆盖的领域。

    简单策略：对比 geo_tags 与锚点 metadata 中的标签覆盖度。
    """
    gaps = []
    geo_tags = set(source.get("geo_tags", []))

    if not geo_tags or not anchors:
        return gaps

    # 统计锚点覆盖的标签
    covered_tags = set()
    for anchor in anchors:
        meta = anchor.get("metadata", {})
        tags_raw = meta.get("geo_tags", "[]")
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            covered_tags.update(tags)
        except Exception:
            pass

    # 未覆盖的标签即为缺口
    uncovered = geo_tags - covered_tags
    for tag in uncovered:
        gaps.append({
            "tag": tag,
            "description": f"标签 '{tag}' 在知识库中缺少相关锚点",
            "created_at": datetime.now().isoformat(),
        })

    return gaps


def _generate_obsidian_note(
    state: Dict[str, Any],
    content: str,
    new_anchors: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
) -> Path | None:
    """生成 Obsidian 笔记。"""
    try:
        month_dir = get_month_dir()
        obsidian_dir = GEO_OUTPUT_ROOT / "obsidian" / month_dir
        obsidian_dir.mkdir(parents=True, exist_ok=True)

        task_id = state.get("current_task_id", "unknown")
        platform = state.get("current_platform", "zhihu")
        source = state.get("current_source", {})
        title = source.get("title", task_id)

        note_name = f"GEO_{task_id}_{platform}.md"
        note_path = obsidian_dir / note_name

        note_content = f"""---
title: {title}
task_id: {task_id}
platform: {platform}
source_agent: {source.get("agent", "")}
created_at: {datetime.now().isoformat()}
tags: {source.get("geo_tags", [])}
---

# {title}

## 生成内容摘要

{content[:500]}...

## 新锚点（{len(new_anchors)} 条）

"""
        for anchor in new_anchors:
            note_content += f"- `{anchor['anchor_id']}`: {anchor['content'][:100]}\n"

        if gaps:
            note_content += f"\n## 知识缺口（{len(gaps)} 个）\n\n"
            for gap in gaps:
                note_content += f"- **{gap['tag']}**: {gap['description']}\n"

        note_content += "\n---\n*由 AKO GEO 知识发酵自动生成*\n"

        note_path.write_text(note_content, encoding="utf-8")
        logger.info("N8_Ferment: Obsidian 笔记写入 %s", note_path)
        return note_path

    except Exception as e:
        logger.error("N8_Ferment: Obsidian 笔记生成失败: %s", e)
        return None


def _get_knowledge_hub(state: Dict[str, Any]) -> Any | None:
    """从 state 或 Hub 全局获取 KnowledgeHub 实例。"""
    if "knowledge_hub" in state:
        return state["knowledge_hub"]

    try:
        import sys
        from ako_geo.config import AKO_HUB_ROOT
        sys.path.insert(0, str(AKO_HUB_ROOT))
        from core.knowledge_hub import KnowledgeHub

        hub = KnowledgeHub(
            db_path=str(AKO_HUB_ROOT / "hub_meta.db"),
            chroma_root=str(AKO_HUB_ROOT / "chroma_db"),
        )
        return hub
    except Exception as e:
        logger.warning("N8_Ferment: 无法初始化 KnowledgeHub: %s", e)
        return None
