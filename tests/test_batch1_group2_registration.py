# -*- coding: utf-8 -*-
"""批1 第2组：business / drawing_inspector / image_analyzer / netwatch / knowledge 接通冒烟。

统一断言（每 agent）：SPOKE_REGISTRY 条目完整、路由关键词命中、适配器可导入。
真实业务链：LLM/图类动作（business 文档生成、image 图像分析）与外部副作用动作
（netwatch 巡检）不入自动化循环，按 AC-09 口径人工在环验收（见 logs/ 验收记录）。
"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"

AGENTS = {
    "AKO_business_agent": ("agents.ako_business_adapter", ["商业"]),
    "AKO_drawing_inspector": ("agents.ako_drawing_inspector", ["审图", "规范"]),
    "AKO_image_analyzer_agent": ("agents.ako_image_analyzer", ["识别", "效果图"]),
    "AKO_netwatch_agent": ("agents.ako_netwatch_adapter", ["监控"]),
    "AKO_knowledge": ("agents.ako_knowledge_adapter", ["知识"]),
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_registry_entries_complete():
    for wid, (module, _kw) in AGENTS.items():
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册到 SPOKE_REGISTRY"
        assert entry["entry_module"] == module, f"{wid} entry_module={entry['entry_module']}"
        assert entry["invoke_mode"] == "importlib", wid
        assert entry["status"] in ("registered", "active"), f"{wid}: {entry['status']}"


def test_routing_keywords():
    routes = _load_keyword_routes()
    for wid, (_module, keywords) in AGENTS.items():
        for kw in keywords:
            assert routes.get(kw) == wid, f"关键词 {kw} 未路由到 {wid}（实际 {routes.get(kw)}）"


def test_adapters_importable():
    for wid, (module, _kw) in AGENTS.items():
        mod = importlib.import_module(module)
        assert callable(getattr(mod, "run", None)), f"{module}.run 缺失"
