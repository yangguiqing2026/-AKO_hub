"""
AKO Hub — ako_geo 节点 N3_Outline
n3_outline.py: 调用 LLM 生成结构化大纲。

文档编号: AGE-TECH-AKO-GEO-001 §4.4
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ako_geo.config import LLM_ROUTE_OUTLINE, PLATFORMS, LLM_MAX_TOKENS

logger = logging.getLogger("ako_geo")

# ── Prompt 模板 ──────────────────────────────────────────────────────
# TODO: 根据实际业务需求完善 Prompt 模板

OUTLINE_PROMPT_TEMPLATE = """你是一位专业的内容营销策划师，擅长将技术成果转化为高质量的营销内容。

## 任务
根据以下素材信息，生成一份结构化的内容大纲（Markdown 格式）。

## 素材信息
- 任务编号: {task_id}
- 来源 Agent: {agent}
- 标题: {title}
- 可公开摘要: {public_abstract}
- 关键断言: {key_claims}
- 话题标签: {geo_tags}
- 目标平台: {platform}

## 知识上下文
{context}

## 大纲要求
1. 包含清晰的章节结构（H2/H3 标题）
2. 在每个关键论点处标注「锚点注入位置」，格式: <!-- ANCHOR: 锚点ID -->
3. 在适当位置标注「商务植入点」，格式: <!-- BIZ: 商务关键词 -->
4. 大纲总字数控制在 500-800 字
5. 开头需要有吸引读者的引子
6. 结尾需要有行动号召（CTA）

## 输出格式
直接输出 Markdown 大纲，不要包含额外说明。
"""


def generate_outline(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N3_Outline: 调用 LLM 生成结构化大纲。

    输入:
        state.current_source: dict  — 当前素材详情（含 public_abstract, key_claims, geo_tags）。
        state.anchors: list[dict]  — 知识锚点列表。
        state.context: str  — 聚合的上下文知识。
        state.current_platform: str  — 目标平台（默认 zhihu）。

    输出:
        state.outline: str  — 生成的大纲（Markdown 格式）。

    LLM 路由:
        primary: deepseek（深度构思）
        fallback: kimi → ollama
    """
    logger.info("N3_Outline: 开始生成大纲")

    source = state.get("current_source", {})
    if not source:
        logger.error("N3_Outline: 无当前素材，跳过")
        return {**state, "outline": "", "error_message": "无当前素材"}

    task_id = state.get("current_task_id", source.get("task_id", "unknown"))
    agent = source.get("agent", "")
    title = source.get("title", "")
    public_abstract = source.get("public_abstract", "")
    key_claims = source.get("key_claims", [])
    geo_tags = source.get("geo_tags", [])
    context = state.get("context", "")
    platform = state.get("current_platform", "zhihu")

    # 构建 Prompt
    prompt = OUTLINE_PROMPT_TEMPLATE.format(
        task_id=task_id,
        agent=agent,
        title=title,
        public_abstract=public_abstract,
        key_claims="; ".join(key_claims) if key_claims else "（无）",
        geo_tags=", ".join(geo_tags) if geo_tags else "（无）",
        platform=platform,
        context=context or "（无额外知识上下文）",
    )

    # 调用 LLM（通过 Hub 路由）
    outline = _call_llm_outline(state, prompt)

    if not outline:
        logger.error("N3_Outline: LLM 调用失败，无大纲输出")
        return {**state, "outline": "", "error_message": "LLM 调用失败"}

    logger.info("N3_Outline: 大纲生成完成，长度 %d 字符", len(outline))

    return {
        **state,
        "outline": outline,
    }


def _call_llm_outline(state: Dict[str, Any], prompt: str) -> str:
    """
    通过 Hub LLM 路由调用大模型生成大纲。

    TODO: 实际部署时对接 Hub 的 call_llm() 接口。
    """
    # 尝试从 state 获取 LLM 路由器
    llm_router = state.get("llm_router")

    if llm_router:
        try:
            response = llm_router.call(
                model=LLM_ROUTE_OUTLINE["primary"],
                prompt=prompt,
                fallback_chain=LLM_ROUTE_OUTLINE["fallback"],
                max_tokens=LLM_MAX_TOKENS,
            )
            return response.get("content", "")
        except Exception as e:
            logger.error("N3_Outline: LLM 路由调用失败: %s", e)

    # 降级：尝试直接调用 Hub API
    try:
        import sys
        from ako_geo.config import AKO_HUB_ROOT
        sys.path.insert(0, str(AKO_HUB_ROOT))
        from hub_api import call_llm

        response = call_llm(
            model=LLM_ROUTE_OUTLINE["primary"],
            prompt=prompt,
            fallback_chain=LLM_ROUTE_OUTLINE["fallback"],
        )
        return response.get("content", "")
    except Exception as e:
        logger.warning("N3_Outline: Hub API 降级失败: %s，使用占位大纲", e)

    # 最终降级：返回占位大纲
    return _generate_placeholder_outline(state)


def _generate_placeholder_outline(state: Dict[str, Any]) -> str:
    """生成占位大纲（LLM 不可用时的降级方案）。"""
    source = state.get("current_source", {})
    title = source.get("title", "未命名成果")
    public_abstract = source.get("public_abstract", "")

    return f"""# {title}

## 引言
{public_abstract[:200]}...

## 核心亮点
<!-- TODO: LLM 不可用，需人工补充大纲 -->

## 技术细节
<!-- TODO: 待补充 -->

## 应用案例
<!-- TODO: 待补充 -->

## 总结与展望
<!-- TODO: 待补充 -->

---
*注: 本大纲为自动生成（LLM 降级），请人工审核后补充完善。*
"""
