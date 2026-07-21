"""
AKO Hub — ako_geo 节点 N1_Filter
n1_filter.py: 过滤候选素材，排除不可公开内容。

文档编号: AGE-TECH-AKO-GEO-001 §4.2
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ako_geo.utils import validate_claims, validate_public_abstract, normalize_tags, load_geo_tags

logger = logging.getLogger("ako_geo")

# 量化值正则
_QUANTITY_RE = re.compile(r'\d+\s*[a-zA-Z\u4e00-\u9fa5]+')


def filter_candidates(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N1_Filter: 过滤 sensitivity != P0 且 public_abstract != "不可公开" 的候选。

    输入:
        state.candidates: list[dict]  — N0_Scan 输出的候选列表。

    输出:
        state.filtered: list[dict]  — 过滤后的候选列表，每条附加 validation_errors/warnings。

    过滤规则:
        1. sensitivity 为 P0 → 跳过。
        2. public_abstract 为 "不可公开" → 跳过。
        3. key_claims 每条必须含量化值，否则标记 validation_error。
        4. public_abstract 长度 < 50 字 → 标记 warning。
        5. geo_tags 非法 → 自动替换为最接近的合法标签。
    """
    logger.info("N1_Filter: 开始过滤 %d 个候选素材", len(state.get("candidates", [])))

    valid_tags = load_geo_tags()
    filtered = []

    for candidate in state.get("candidates", []):
        task_id = candidate.get("task_id", "unknown")
        sensitivity = candidate.get("sensitivity", "P0")
        public_abstract = candidate.get("public_abstract", "")

        # 规则 1: sensitivity P0 跳过
        if sensitivity == "P0":
            logger.info("N1_Filter: 跳过 P0 素材: %s", task_id)
            continue

        # 规则 2: public_abstract 为 "不可公开" 跳过
        if public_abstract.strip() == "不可公开":
            logger.info("N1_Filter: 跳过不可公开素材: %s", task_id)
            continue

        # 规则 3: key_claims 量化值校验
        key_claims = candidate.get("key_claims", [])
        claim_errors, claim_warnings = validate_claims(key_claims)
        if claim_errors:
            logger.warning("N1_Filter: %s key_claims 校验失败: %s", task_id, claim_errors)
            candidate["validation_errors"] = claim_errors
            # 标记但不跳过，留给后续人工确认
            # TODO: 根据业务策略决定是否跳过

        # 规则 4: public_abstract 长度校验
        abstract_warnings = validate_public_abstract(public_abstract)
        if abstract_warnings:
            logger.warning("N1_Filter: %s public_abstract 警告: %s", task_id, abstract_warnings)
            candidate.setdefault("validation_warnings", []).extend(abstract_warnings)

        # 规则 5: geo_tags 规范化
        geo_tags = candidate.get("geo_tags", [])
        if geo_tags and valid_tags:
            candidate["geo_tags"] = normalize_tags(geo_tags, valid_tags)

        filtered.append(candidate)

    logger.info("N1_Filter: 过滤后剩余 %d 个候选素材", len(filtered))

    return {
        **state,
        "filtered": filtered,
    }
