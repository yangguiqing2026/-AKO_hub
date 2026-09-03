# -*- coding: utf-8 -*-
"""批1：layout 接通冒烟——注册/路由就位 + 适配器协议级错误透传（环境缺 reportlab 时如实报错）。

口径：layout 真实 PDF/PPT 链依赖 reportlab/python-pptx/dashscope/openai，
hub 运行环境（系统 python）当前未安装（2026-09-03 核实三个候选环境均缺）。
本用例验证接线与兜底正确性；AC-04 真实排版链挂账待环境装依赖后验收。
"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "排版": "AKO_layout_agent",
    "海报": "AKO_layout_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_layout_agent")
    assert entry is not None, "AKO_layout_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_layout_adapter"
    assert entry["invoke_mode"] == "importlib"
    assert entry["status"] in ("registered", "active"), entry["status"]
    assert entry["source_dir"].endswith("AKO_layout_agent")


def test_routing_keywords_target_layout():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_callable():
    mod = importlib.import_module("agents.ako_layout_adapter")
    assert callable(mod.run)


def test_protocol_error_chain_without_reportlab():
    """环境缺 reportlab 时：适配器必须三字段返回 error（ImportError 透传），不得裸抛。"""
    mod = importlib.import_module("agents.ako_layout_adapter")
    result = mod.run(intent="排版演示", _hub_output_dir="")
    assert result["error"], "缺 reportlab 环境应返回 error 而非裸抛异常"
    assert isinstance(result["output_files"], list)
    assert isinstance(result["summary"], str)
