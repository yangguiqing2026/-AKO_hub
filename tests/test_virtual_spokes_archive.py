# -*- coding: utf-8 -*-
"""批1 收尾：hub 内虚拟 spoke 归档核对（不改外部工程，仅确认注册与可导入）。

虚拟 spoke = hub 仓库内实现的工作流实体（无 D:\AKO 独立 Agent 目录）：
chat / reports / form_extractor / geo / 工作流。
历史漂移：工作流实体以中文 id 'AKO工作流' 注册（非 AKO_workflow）——归档声明，待 §九 清扫统一。
"""
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

VIRTUAL_EN = {
    "AKO_chat": "agents.ako_chat_adapter",
    "AKO_reports": "agents.ako_reports_adapter",
    "AKO_form_extractor": "agents.ako_form_extractor_adapter",
    "AKO_geo": "agents.ako_geo_adapter",
}
WORKFLOW_ZH_ID = "AKO工作流"
WORKFLOW_MODULE = "agents.ako_workflow_adapter"


def test_virtual_spokes_registered_importable():
    for wid, module in VIRTUAL_EN.items():
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册"
        assert entry["status"] in ("registered", "active"), f"{wid}: {entry['status']}"
        mod = importlib.import_module(module)
        assert callable(getattr(mod, "run", None)), f"{module}.run 缺失"


def test_workflow_zh_id_drift_documented():
    """工作流实体当前以中文 id 'AKO工作流' 注册（漂移声明）。清扫后应改为英文 id 并同步本用例。"""
    entry = get_spoke_by_id(WORKFLOW_ZH_ID)
    assert entry is not None, f"{WORKFLOW_ZH_ID} 未注册"
    assert entry["status"] in ("registered", "active")
    mod = importlib.import_module(WORKFLOW_MODULE)
    assert callable(getattr(mod, "run", None)), f"{WORKFLOW_MODULE}.run 缺失"
