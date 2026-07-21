"""
AKO Hub — ako_geo 节点 N6_Publish
n6_publish.py: 生成发布包（标题、摘要、标签、正文、封面建议）。

文档编号: AGE-TECH-AKO-GEO-001 §4.7
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("ako_geo")


def prepare_publish(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N6_Publish: 生成发布包。

    输入:
        state.content: str  — 平台适配后的正文内容。
        state.current_platform: str  — 目标平台。
        state.current_source: dict  — 当前素材详情。

    输出:
        state.publish_pack: dict  — 发布包，包含:
            - task_id: str
            - platform: str
            - title: str
            - abstract: str
            - tags: list[str]
            - content: str
            - cover_image_hint: str?
            - meta: dict（status, created_at, source_agent）
    """
    logger.info("N6_Publish: 生成发布包，平台=%s", state.get("current_platform"))

    content = state.get("content", "")
    platform = state.get("current_platform", "zhihu")
    source = state.get("current_source", {})

    if not content:
        logger.error("N6_Publish: 无正文内容，跳过")
        return {**state, "publish_pack": None, "error_message": "无正文内容"}

    task_id = state.get("current_task_id", source.get("task_id", "unknown"))
    title = source.get("title", "未命名成果")
    geo_tags = source.get("geo_tags", [])
    agent = source.get("agent", "")

    # 生成标题（从内容第一行提取或从素材标题生成）
    publish_title = _generate_title(content, title, platform)

    # 生成摘要（取内容前 200 字或素材 public_abstract）
    abstract = _generate_abstract(content, source)

    # 封面图建议
    cover_hint = _generate_cover_hint(source, geo_tags)

    # 构建发布包
    publish_pack = {
        "task_id": task_id,
        "platform": platform,
        "title": publish_title,
        "abstract": abstract,
        "tags": geo_tags,
        "content": content,
        "cover_image_hint": cover_hint,
        "meta": {
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "source_agent": agent,
            "source_task_id": task_id,
            "sensitivity": source.get("sensitivity", "P2"),
        },
    }

    logger.info("N6_Publish: 发布包生成完成，标题=%s", publish_title[:30])

    return {
        **state,
        "publish_pack": publish_pack,
    }


def _generate_title(content: str, fallback_title: str, platform: str) -> str:
    """
    生成发布标题。

    策略：
    1. 从内容第一行提取（如果是 Markdown 标题）。
    2. 否则使用素材标题。
    3. 根据平台做长度适配。
    """
    # 尝试从内容提取标题
    lines = content.strip().split("\n")
    for line in lines[:5]:
        line = line.strip()
        if line.startswith("# "):
            extracted = line[2:].strip()
            if extracted:
                return _truncate_title(extracted, platform)

    # 使用素材标题
    return _truncate_title(fallback_title, platform)


def _truncate_title(title: str, platform: str) -> str:
    """根据平台限制截断标题。"""
    limits = {
        "zhihu": 50,
        "wechat": 64,
        "douyin": 30,
        "baijia": 50,
    }
    max_len = limits.get(platform, 50)
    if len(title) > max_len:
        return title[:max_len - 3] + "..."
    return title


def _generate_abstract(content: str, source: Dict[str, Any]) -> str:
    """生成发布摘要。"""
    # 优先使用素材的 public_abstract
    public_abstract = source.get("public_abstract", "")
    if public_abstract and len(public_abstract) >= 50:
        return public_abstract[:200]

    # 从内容提取前 200 字
    # 去除 Markdown 标记
    clean = content
    for prefix in ["# ", "## ", "### ", "- ", "* "]:
        clean = clean.replace(prefix, "")

    # 取前 200 字
    abstract = clean[:200].strip()
    if len(clean) > 200:
        abstract = abstract.rsplit("。", 1)[0] + "。" if "。" in abstract else abstract + "..."

    return abstract


def _generate_cover_hint(source: Dict[str, Any], geo_tags: list) -> str:
    """生成封面图建议。"""
    # 从素材的 output_files 中查找图片
    output_files = source.get("output_files", [])
    if output_files:
        for f in output_files:
            if any(f.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"]):
                return f

    # 从 geo_tags 生成关键词建议
    if geo_tags:
        return f"建议封面关键词: {', '.join(geo_tags[:3])}"

    return "建议使用行业相关图片"
