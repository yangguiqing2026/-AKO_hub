"""
AKO Hub — ako_geo 节点 N7_Store
n7_store.py: 将发布包写入文件系统，生成审核日志。

文档编号: AGE-TECH-AKO-GEO-001 §4.8
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from ako_geo.config import GEO_OUTPUT_ROOT, FAILED_DIR, PLATFORM_EXT
from ako_geo.utils import get_month_dir, slugify_filename

# 统一命名模块
_SHARED_DIR = Path("D:/AKO_shared")
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
from naming import generate_filename, get_file_id

logger = logging.getLogger("ako_geo")


def store_output(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    N7_Store: 将发布包写入文件系统。

    输入:
        state.publish_pack: dict  — 发布包。
        state.current_task_id: str  — 任务 ID。
        state.current_platform: str  — 目标平台。
        state.review_status: str  — 审核状态。
        state.review_comment: str?  — 审核意见。

    输出:
        state.file_paths: list[Path]  — 生成的文件路径列表。

    文件命名规范:
        正文: {date}_{source_task_id}_{platform}.{ext}
        元数据: {date}_{source_task_id}_{platform}.json
        审核记录: {date}_{source_task_id}_{platform}_review.yaml
    """
    logger.info("N7_Store: 开始写入文件")

    publish_pack = state.get("publish_pack")
    if not publish_pack:
        logger.error("N7_Store: 无发布包，跳过")
        return {**state, "file_paths": []}

    task_id = state.get("current_task_id", publish_pack.get("task_id", "unknown"))
    platform = state.get("current_platform", publish_pack.get("platform", "zhihu"))
    review_status = state.get("review_status", "pending")

    # 确定输出目录
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_dir = get_month_dir(date_str)

    # 审核失败 → failed/ 目录
    if review_status == "failed":
        output_dir = FAILED_DIR / month_dir
    else:
        output_dir = GEO_OUTPUT_ROOT / month_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    file_paths = []
    ext = PLATFORM_EXT.get(platform, "md")

    # 1. 写入正文文件（统一命名 + 首页嵌入编号）
    content_filename = generate_filename("GEO内容", ext, output_dir)
    content_file = output_dir / content_filename
    file_id = get_file_id(content_filename)
    content = publish_pack.get("content", "")
    # 首页嵌入文件编号（Markdown/HTML 兼容格式）
    if ext == "md":
        content = f"> 编号：{file_id}\n\n{content}"
    else:
        content = f"<!-- 编号：{file_id} -->\n{content}"
    content_file.write_text(content, encoding="utf-8")
    file_paths.append(content_file)
    logger.info("N7_Store: 正文写入 %s", content_file)

    # 2. 写入元数据 JSON
    meta_file = output_dir / slugify_filename(date_str, task_id, platform, "json")
    meta_data = {
        "task_id": task_id,
        "platform": platform,
        "title": publish_pack.get("title", ""),
        "abstract": publish_pack.get("abstract", ""),
        "tags": publish_pack.get("tags", []),
        "cover_image_hint": publish_pack.get("cover_image_hint"),
        "meta": publish_pack.get("meta", {}),
        "generated_at": datetime.now().isoformat(),
    }
    meta_file.write_text(
        json.dumps(meta_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    file_paths.append(meta_file)
    logger.info("N7_Store: 元数据写入 %s", meta_file)

    # 3. 写入审核记录 YAML
    review_file = output_dir / slugify_filename(date_str, task_id, platform + "_review", "yaml")
    review_data = {
        "task_id": task_id,
        "platform": platform,
        "review_status": review_status,
        "review_comment": state.get("review_comment"),
        "review_loop_count": state.get("review_loop_count", 0),
        "reviewed_at": datetime.now().isoformat(),
        "source_agent": state.get("current_agent", ""),
        "files_generated": [str(p) for p in file_paths],
    }
    review_file.write_text(
        yaml.dump(review_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    file_paths.append(review_file)
    logger.info("N7_Store: 审核记录写入 %s", review_file)

    # 4. 追加到月度 review_log.yaml
    review_log_path = output_dir / f"{date_str}_review_log.yaml"
    _append_review_log(review_log_path, review_data)

    logger.info("N7_Store: 文件写入完成，共 %d 个文件", len(file_paths))

    return {
        **state,
        "file_paths": file_paths,
    }


def _append_review_log(log_path: Path, entry: Dict[str, Any]) -> None:
    """追加审核记录到月度 review_log.yaml。"""
    existing = []
    if log_path.exists():
        try:
            data = yaml.safe_load(log_path.read_text("utf-8"))
            if isinstance(data, list):
                existing = data
        except Exception:
            pass

    existing.append(entry)
    log_path.write_text(
        yaml.dump(existing, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
