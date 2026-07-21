"""
AKO Hub — ako_geo 辅助工具函数
utils.py: 校验、标签管理、文件名生成等通用工具。

文档编号: AGE-TECH-AKO-GEO-001 §3
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ako_geo.config import (
    HUB_GEO_TAGS_FILE,
    GEO_OUTPUT_ROOT,
    LOG_DIR,
    PLATFORM_EXT,
)

logger = logging.getLogger("ako_geo")


# ── 日志初始化 ───────────────────────────────────────────────────────

def setup_geo_logger() -> logging.Logger:
    """
    初始化 ako_geo 日志处理器。
    
    输出格式为 JSON Lines，写入 D:\\AKO_Hub\\logs\\geo_YYYYMMDD.log。
    """
    logger = logging.getLogger("ako_geo")
    
    if logger.handlers:
        return logger  # 已初始化，避免重复添加
    
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"geo_{datetime.now().strftime('%Y%m%d')}.log"
    
    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        '{"timestamp":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    return logger


# ── key_claims 校验 ──────────────────────────────────────────────────

# 量化值正则：阿拉伯数字 + 可选单位
_QUANTITY_RE = re.compile(r'\d+\s*[a-zA-Z\u4e00-\u9fa5]+')


def validate_claims(claims: List[str]) -> Tuple[List[str], List[str]]:
    """
    校验 key_claims 列表：每条必须含阿拉伯数字+单位。
    
    Args:
        claims: 原始断言列表。
    
    Returns:
        (errors, warnings):
            errors: 不含量化值的断言索引描述列表。
            warnings: 其他警告。
    """
    errors = []
    warnings = []
    
    for i, claim in enumerate(claims):
        if not _QUANTITY_RE.search(claim):
            errors.append(f"key_claims[{i}] 缺少量化值（数字+单位）: {claim[:30]}...")
    
    return errors, warnings


def validate_public_abstract(text: str) -> List[str]:
    """
    校验 public_abstract 长度。
    
    长度 < 50 字时返回警告列表，否则返回空列表。
    """
    warnings = []
    if len(text) < 50:
        warnings.append(f"public_abstract 长度不足 50 字（当前 {len(text)} 字），需人工确认")
    return warnings


# ── 标签管理 ─────────────────────────────────────────────────────────

def load_geo_tags() -> List[str]:
    """
    从 hub_geo_tags.json 加载合法标签白名单。
    
    Returns:
        合法标签字符串列表。若文件不存在返回空列表。
    """
    if not HUB_GEO_TAGS_FILE.exists():
        logger.warning("合法标签文件不存在: %s，使用空白名单", HUB_GEO_TAGS_FILE)
        return []
    
    try:
        data = json.loads(HUB_GEO_TAGS_FILE.read_text("utf-8"))
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "tags" in data:
            return data["tags"]
        return []
    except Exception as e:
        logger.error("加载合法标签文件失败: %s", e)
        return []


def normalize_tags(tags: List[str], valid_tags: Optional[List[str]] = None) -> List[str]:
    """
    将标签列表规范化：非法标签替换为最接近的合法标签。
    
    匹配策略：简单子串包含 → 编辑距离最近（降级）。
    
    Args:
        tags: 原始标签列表。
        valid_tags: 合法标签白名单，为 None 时自动加载。
    
    Returns:
        规范化后的标签列表。
    """
    if valid_tags is None:
        valid_tags = load_geo_tags()
    
    if not valid_tags:
        return tags  # 无白名单时原样返回
    
    normalized = []
    for tag in tags:
        tag = tag.strip()
        if tag in valid_tags:
            normalized.append(tag)
        else:
            # 尝试子串匹配
            matched = None
            for vt in valid_tags:
                if tag in vt or vt in tag:
                    matched = vt
                    break
            
            if matched:
                logger.info("标签 '%s' 替换为最接近的合法标签: '%s'", tag, matched)
                normalized.append(matched)
            else:
                # 编辑距离最近（简单实现）
                best = min(valid_tags, key=lambda vt: _edit_distance(tag, vt))
                logger.info("标签 '%s' 替换为编辑距离最近的合法标签: '%s'", tag, best)
                normalized.append(best)
    
    return list(dict.fromkeys(normalized))  # 去重保序


def _edit_distance(s1: str, s2: str) -> int:
    """简单 Levenshtein 编辑距离（用于标签模糊匹配）。"""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    
    return prev_row[-1]


# ── 文件名生成 ───────────────────────────────────────────────────────

def slugify_filename(
    date_str: str,
    task_id: str,
    platform: str,
    ext: Optional[str] = None,
) -> str:
    """
    按命名规范生成输出文件名。
    
    命名规范: {date}_{source_task_id}_{platform}.{ext}
    
    Args:
        date_str: 日期字符串，格式 YYYY-MM-DD。
        task_id: 来源任务 ID（geo.yaml 中的 task_id）。
        platform: 目标平台名称。
        ext: 文件扩展名，为 None 时从 PLATFORM_EXT 读取。
    
    Returns:
        规范化的文件名字符串。
    """
    if ext is None:
        ext = PLATFORM_EXT.get(platform, "md")
    
    # 清理 task_id 中的非法字符
    safe_task_id = re.sub(r'[^\w\-]', '_', task_id)
    
    return f"{date_str}_{safe_task_id}_{platform}.{ext}"


def get_month_dir(date_str: Optional[str] = None) -> str:
    """
    获取月份子目录名（YYYY-MM 格式）。
    
    Args:
        date_str: 日期字符串（YYYY-MM-DD），为 None 时使用当前日期。
    
    Returns:
        月份目录名，如 "2025-01"。
    """
    if date_str:
        return date_str[:7]  # YYYY-MM
    return datetime.now().strftime("%Y-%m")


# ── 内容哈希（去重） ─────────────────────────────────────────────────

def compute_content_hash(file_path: Path) -> str:
    """
    计算文件内容的 MD5 哈希值，用于幂等性去重。
    
    Args:
        file_path: 文件路径。
    
    Returns:
        MD5 哈希字符串。
    """
    content = file_path.read_bytes()
    return hashlib.md5(content).hexdigest()


def make_dedup_key(task_id: str, content_hash: str) -> str:
    """
    生成去重键：task_id + content_hash。
    
    Args:
        task_id: 任务 ID。
        content_hash: 内容哈希。
    
    Returns:
        去重键字符串。
    """
    return f"{task_id}::{content_hash}"


# ── geo.yaml 加载 ────────────────────────────────────────────────────

def load_geo_yaml(file_path: Path) -> Dict[str, Any]:
    """
    安全加载 geo.yaml 文件。
    
    Args:
        file_path: geo.yaml 文件路径。
    
    Returns:
        解析后的字典。
    
    Raises:
        FileNotFoundError: 文件不存在。
        yaml.YAMLError: YAML 解析失败。
    """
    if not file_path.exists():
        raise FileNotFoundError(f"geo.yaml 不存在: {file_path}")
    
    content = file_path.read_text("utf-8")
    data = yaml.safe_load(content)
    
    if not isinstance(data, dict):
        raise ValueError(f"geo.yaml 根节点必须是字典: {file_path}")
    
    return data


# ── 输出目录管理 ─────────────────────────────────────────────────────

def ensure_output_dirs() -> None:
    """确保所有输出目录存在。"""
    for d in [GEO_OUTPUT_ROOT, LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    
    # 按月目录在运行时动态创建
    month_dir = GEO_OUTPUT_ROOT / get_month_dir()
    month_dir.mkdir(parents=True, exist_ok=True)
    
    obsidian_month = GEO_OUTPUT_ROOT / "obsidian" / get_month_dir()
    obsidian_month.mkdir(parents=True, exist_ok=True)
    
    failed_month = GEO_OUTPUT_ROOT / "failed" / get_month_dir()
    failed_month.mkdir(parents=True, exist_ok=True)
