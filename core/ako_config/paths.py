"""
AKO 统一配置 — 路径工具

提供跨项目路径解析和目录创建工具。
"""

import os
from pathlib import Path
from typing import Optional


def resolve_path(path_str: str, anchor: Optional[str] = None) -> str:
    """
    将路径字符串解析为规范化的绝对路径。

    Args:
        path_str: 原始路径（支持相对 / 绝对 / 含 ~ ）
        anchor: 相对路径的锚点目录（默认为 cwd）

    Returns:
        规范化后的绝对路径（正斜杠）
    """
    if not path_str:
        return ""

    p = Path(path_str).expanduser()

    if not p.is_absolute():
        base = Path(anchor) if anchor else Path.cwd()
        p = base / p

    return str(p.resolve()).replace("\\", "/")


def ensure_dir(path_str: str) -> str:
    """
    确保目录存在，不存在则创建。

    Args:
        path_str: 目录路径

    Returns:
        解析后的绝对路径
    """
    resolved = resolve_path(path_str)
    Path(resolved).mkdir(parents=True, exist_ok=True)
    return resolved


def relative_to(path_str: str, base: str) -> str:
    """
    计算 path 相对于 base 的路径。

    Args:
        path_str: 目标路径
        base: 基准路径

    Returns:
        相对路径字符串
    """
    try:
        return str(Path(path_str).resolve().relative_to(Path(base).resolve())).replace("\\", "/")
    except ValueError:
        return resolve_path(path_str)


def is_under(child: str, parent: str) -> bool:
    """
    判断 child 路径是否在 parent 目录下。
    """
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False
