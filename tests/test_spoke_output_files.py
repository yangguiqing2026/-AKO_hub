"""注册文件清单的裁决规则（2026-09-14）。

背景：workflow_caller 会快照 spoke 的输出目录，把运行期间新出现的文件**全部**
并入注册集（兜底机制，防 spoke 漏报）。但 writer 的产物目录 file_bus/writer_output
里同时存放中间件（md 草稿 / 插图 / outline.md），于是工作台结果卡片会列出一串
下载链接 —— 用户要的是「只显示 docx」。

故引入注册表开关 file_scan="spoke_only"：该 spoke 以自报的 output_files 为准，
跳过目录扫描兜底。未声明该开关的 spoke 行为完全不变（兜底仍在）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from master.nodes import _resolve_output_files  # noqa: E402


def test_spoke_only_uses_reported_list() -> None:
    """声明 file_scan=spoke_only 时，目录扫描发现的中间件不得并入。"""
    spoke = {"workflow_id": "AKO_writer_agent", "file_scan": "spoke_only"}
    reported = [r"D:\bus\writer_output\WR-1\a.docx"]
    scanned = [r"D:\bus\writer_output\WR-1\a.docx", r"D:\bus\writer_output\WR-1\outline.md"]
    assert _resolve_output_files(spoke, reported, scanned) == reported


def test_spoke_only_falls_back_when_nothing_reported() -> None:
    """spoke 一个都没报时仍走兜底 —— 否则漏报的 spoke 会在工作台彻底看不到产物。"""
    spoke = {"file_scan": "spoke_only"}
    scanned = [r"D:\bus\x\a.docx"]
    assert _resolve_output_files(spoke, [], scanned) == scanned


def test_default_behavior_unchanged() -> None:
    """未声明开关的 spoke：维持原行为（自报 + 扫描 取并集）。"""
    spoke = {"workflow_id": "AKO_quote_agent"}
    reported = [r"D:\bus\quote_output\q.json"]
    scanned = [r"D:\bus\quote_output\q.json", r"D:\bus\quote_output\p.pdf"]
    assert set(_resolve_output_files(spoke, reported, scanned)) == {reported[0], scanned[1]}


def test_flag_is_case_insensitive_and_trimmed() -> None:
    spoke = {"file_scan": "  Spoke_Only  "}
    reported = [r"D:\bus\a.docx"]
    assert _resolve_output_files(spoke, reported, [r"D:\bus\b.md"]) == reported
