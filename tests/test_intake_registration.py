# -*- coding: utf-8 -*-
"""批0：intake 注册层冒烟——SPOKE_REGISTRY 条目、routing 关键词、适配器可导入。"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "帮我": "AKO_hub_intake_agent",
    "我要": "AKO_hub_intake_agent",
    "工单": "AKO_hub_intake_agent",
    "大门": "AKO_hub_intake_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_hub_intake_agent")
    assert entry is not None, "AKO_hub_intake_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_intake_adapter"
    assert entry["entry_function"] == "run"
    assert entry["invoke_mode"] == "importlib"
    assert entry["status"] == "registered"
    assert entry["source_dir"].endswith("AKO_hub_intake_agent")


def test_routing_keywords_target_intake():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_and_run_callable():
    mod = importlib.import_module("agents.ako_intake_adapter")
    assert callable(getattr(mod, "run", None))
    assert callable(getattr(mod, "get_intake_status", None))
