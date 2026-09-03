# -*- coding: utf-8 -*-
"""批1 收尾：hub 内虚拟 spoke 归档核对（不改外部工程，仅确认注册与可导入）。

虚拟 spoke = hub 仓库内实现的工作流实体（无 D:\AKO 独立 Agent 目录）：
chat / reports / form_extractor / geo / AKO_workflow（§九 清扫后统一英文 id，
历史中文 'AKO工作流' 已废弃——见 tests/test_naming_sweep.py 固化）。
"""
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

VIRTUAL = {
    "AKO_chat": "agents.ako_chat_adapter",
    "AKO_reports": "agents.ako_reports_adapter",
    "AKO_form_extractor": "agents.ako_form_extractor_adapter",
    "AKO_geo": "agents.ako_geo_adapter",
    "AKO_workflow": "agents.ako_workflow_adapter",
}


def test_virtual_spokes_registered_importable():
    for wid, module in VIRTUAL.items():
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册"
        assert entry["status"] in ("registered", "active"), f"{wid}: {entry['status']}"
        mod = importlib.import_module(module)
        assert callable(getattr(mod, "run", None)), f"{module}.run 缺失"


def test_legacy_zh_id_deprecated():
    """§九 清扫固化：历史中文 id 'AKO工作流' 不得再注册。"""
    assert get_spoke_by_id("AKO工作流") is None, "中文 id 'AKO工作流' 仍存在，清扫未生效"
