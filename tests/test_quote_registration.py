# -*- coding: utf-8 -*-
"""批1：quote 接通冒烟——注册条目、路由关键词、适配器直连报价引擎真实链路。"""
import importlib
import json
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "报价": "AKO_quote_agent",
    "成本": "AKO_quote_agent",
    "预算": "AKO_quote_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_quote_agent")
    assert entry is not None, "AKO_quote_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_quote_adapter"
    assert entry["invoke_mode"] == "importlib"
    # registered=新注册 / active=已上线；deprecated 视为未接通
    assert entry["status"] in ("registered", "active"), entry["status"]
    assert entry["source_dir"].endswith("AKO_quote_agent")


def test_routing_keywords_target_quote():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_callable():
    mod = importlib.import_module("agents.ako_quote_adapter")
    assert callable(mod.run)


def test_real_quote_chain():
    """真实链路：intent 解析面积/墙型/厚度 → quote_engine 计价 → JSON 落盘 → 三字段。
    纯规则引擎（无 LLM/无网络），报价内容变化由定价配置决定，用例只断言链路与产出形状。"""
    import tempfile

    mod = importlib.import_module("agents.ako_quote_adapter")
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="报价: 200㎡外墙150mm", project_tag="taoli_test", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        assert result["output_files"] and Path(result["output_files"][0]).exists()
        assert "元" in result["summary"], result["summary"]
        data = json.loads(Path(result["output_files"][0]).read_text(encoding="utf-8"))
        assert data["result"]["total"] > 0
        assert data["input"]["area"] == 200.0
        assert data["input"]["wall_type"] == "外墙"
