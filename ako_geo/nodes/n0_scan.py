"""
AKO Hub — ako_geo 节点 N0_Scan
n0_scan.py: 扫描各业务 Agent 输出目录中的 geo.yaml 文件。

文档编号: AGE-TECH-AKO-GEO-001 §4.1
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from ako_geo.config import AKO_HUB_ROOT, GEO_YAML_GLOB_PATTERN
from ako_geo.utils import load_geo_yaml, compute_content_hash, make_dedup_key

logger = logging.getLogger("ako_geo")


def scan_sources(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N0_Scan: 扫描 D:\\AKO_Hub\\*\\output\\*\\geo.yaml，收集候选素材。

    输入:
        state.sources: list[Path]  — 手动指定的扫描路径（可选，为空时自动 glob）。

    输出:
        state.candidates: list[dict]  — 解析后的候选素材列表（含 source_path、content_hash）。
        state.processed_task_ids: list[str]  — 已处理的 task_id 列表（去重用）。

    幂等性:
        通过 task_id + md5(content) 去重，避免重复处理。
    """
    logger.info("N0_Scan: 开始扫描 geo.yaml 素材")

    # 确定扫描路径
    if state.get("sources"):
        scan_paths = [Path(p) for p in state["sources"]]
    else:
        # 自动 glob：D:\AKO_Hub\*\output\*\geo.yaml
        scan_paths = sorted(AKO_HUB_ROOT.glob(GEO_YAML_GLOB_PATTERN))
        # 也扫描子目录（兼容多级结构）
        scan_paths += sorted(AKO_HUB_ROOT.rglob("geo.yaml"))
        # 去重
        scan_paths = list({p.resolve() for p in scan_paths})

    logger.info("N0_Scan: 发现 %d 个 geo.yaml 文件", len(scan_paths))

    # 已处理的 task_id 集合（去重）
    processed_set = set(state.get("processed_task_ids", []))

    candidates = []
    for path in scan_paths:
        try:
            data = load_geo_yaml(path)
            content_hash = compute_content_hash(path)
            task_id = data.get("task_id", "")
            dedup_key = make_dedup_key(task_id, content_hash)

            if dedup_key in processed_set or task_id in processed_set:
                logger.debug("N0_Scan: 跳过已处理: %s", task_id)
                continue

            # 附加元信息
            data["source_path"] = str(path)
            data["content_hash"] = content_hash
            candidates.append(data)
            logger.info("N0_Scan: 收集候选素材: task_id=%s, agent=%s", task_id, data.get("agent"))

        except Exception as e:
            logger.warning("N0_Scan: 加载失败 %s: %s", path, e)
            continue

    logger.info("N0_Scan: 有效候选 %d 个（去重后）", len(candidates))

    return {
        **state,
        "candidates": candidates,
    }
