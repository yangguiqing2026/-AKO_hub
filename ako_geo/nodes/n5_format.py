"""
AKO Hub — ako_geo 节点 N5_Format
n5_format.py: 按平台模板适配内容格式。

文档编号: AGE-TECH-AKO-GEO-001 §4.6
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from ako_geo.config import TEMPLATES_DIR, PLATFORM_EXT, LLM_ROUTE_FORMAT_LONG, LLM_ROUTE_FORMAT_SHORT

logger = logging.getLogger("ako_geo")


def format_platform(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N5_Format: 按平台模板适配内容格式。

    输入:
        state.outline: str  — 审核通过的大纲。
        state.current_platform: str  — 目标平台。
        state.current_source: dict  — 当前素材详情。

    输出:
        state.content: str  — 平台适配后的正文内容。

    LLM 路由:
        长文（zhihu/wechat/baijia）: kimi（长文润色）
        短文案（douyin）: qwen（短文案/标题）
    """
    logger.info("N5_Format: 开始平台适配，平台=%s", state.get("current_platform"))

    outline = state.get("outline", "")
    platform = state.get("current_platform", "zhihu")
    source = state.get("current_source", {})

    if not outline:
        logger.error("N5_Format: 无大纲内容，跳过")
        return {**state, "content": "", "error_message": "无大纲内容"}

    # 加载平台模板
    template = _load_template(platform)

    # 根据平台选择 LLM 路由
    if platform == "douyin":
        # 抖音：短文案，标题党
        content = _call_llm_format(state, outline, template, platform, short=True)
    else:
        # 知乎/微信/百家：长文润色
        content = _call_llm_format(state, outline, template, platform, short=False)

    if not content:
        logger.warning("N5_Format: LLM 调用失败，使用原始大纲")
        content = outline

    logger.info("N5_Format: 平台适配完成，长度 %d 字符", len(content))

    return {
        **state,
        "content": content,
    }


def _load_template(platform: str) -> str:
    """加载平台模板文件。"""
    template_file = TEMPLATES_DIR / f"{platform}_template.md"

    if template_file.exists():
        try:
            return template_file.read_text("utf-8")
        except Exception as e:
            logger.warning("N5_Format: 加载模板失败 %s: %s", template_file, e)

    # 返回默认模板
    return _get_default_template(platform)


def _get_default_template(platform: str) -> str:
    """返回平台默认模板。"""
    templates = {
        "zhihu": """# {title}

{content}

---
*本文由 AKO GEO 智能生成 | 话题: {tags}*
""",
        "wechat": """# {title}

{content}

---
**关注获取更多行业洞察**
*话题: {tags}*
""",
        "douyin": """【{title}】

{content}

#{tags} #行业洞察 #技术创新
""",
        "baijia": """# {title}

{content}

---
*来源: AKO GEO 智能内容平台 | 话题: {tags}*
""",
    }
    return templates.get(platform, "# {title}\n\n{content}\n")


def _call_llm_format(
    state: Dict[str, Any],
    outline: str,
    template: str,
    platform: str,
    short: bool = False,
) -> str:
    """
    通过 Hub LLM 路由调用大模型进行平台适配。

    TODO: 实际部署时对接 Hub 的 call_llm() 接口。
    """
    source = state.get("current_source", {})
    title = source.get("title", "")
    geo_tags = source.get("geo_tags", [])
    tags_str = " #".join(geo_tags) if geo_tags else "行业洞察"

    if short:
        prompt = _build_short_prompt(outline, title, tags_str, platform)
        route = LLM_ROUTE_FORMAT_SHORT
    else:
        prompt = _build_long_prompt(outline, template, title, tags_str, platform)
        route = LLM_ROUTE_FORMAT_LONG

    # 尝试从 state 获取 LLM 路由器
    llm_router = state.get("llm_router")
    if llm_router:
        try:
            response = llm_router.call(
                model=route["primary"],
                prompt=prompt,
                fallback_chain=route["fallback"],
            )
            return response.get("content", "")
        except Exception as e:
            logger.error("N5_Format: LLM 路由调用失败: %s", e)

    # 降级：尝试 Hub API
    try:
        import sys
        from ako_geo.config import AKO_HUB_ROOT
        sys.path.insert(0, str(AKO_HUB_ROOT))
        from hub_api import call_llm

        response = call_llm(
            model=route["primary"],
            prompt=prompt,
            fallback_chain=route["fallback"],
        )
        return response.get("content", "")
    except Exception as e:
        logger.warning("N5_Format: Hub API 降级失败: %s", e)

    # 最终降级：模板填充
    source = state.get("current_source", {})
    abstract = source.get("public_abstract", "")
    return template.format(
        title=title,
        abstract=abstract,
        content=outline,
        tags=tags_str,
    )


def _build_long_prompt(outline: str, template: str, title: str, tags: str, platform: str) -> str:
    """构建长文润色 Prompt。"""
    return f"""你是一位资深内容编辑，擅长将技术大纲润色为高质量的{platform}平台文章。

## 原始大纲
{outline}

## 平台模板
{template}

## 要求
1. 保持技术准确性，不编造数据
2. 语言流畅，适合{platform}平台读者阅读
3. 适当增加过渡句和案例说明
4. 标题: {title}
5. 话题标签: {tags}
6. 输出完整文章（Markdown 格式）

请直接输出文章内容:
"""


def _build_short_prompt(outline: str, title: str, tags: str, platform: str) -> str:
    """构建短文案 Prompt（抖音等）。"""
    return f"""你是一位短视频文案策划师，将技术内容转化为{platform}平台的吸睛文案。

## 原始内容
{outline}

## 要求
1. 标题: 基于「{title}」创作一个吸睛标题（15字以内）
2. 正文: 100-200字，口语化，有节奏感
3. 话题标签: {tags}
4. 结尾加行动号召（关注/点赞/评论）

请直接输出文案:
"""
