# -*- coding: utf-8 -*-
"""批1：law 接通冒烟——注册条目、路由关键词、适配器直连核心类真实自检链路。"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "法律": "AKO_law_agent",
    "合规": "AKO_law_agent",
    "合同": "AKO_law_agent",
    "法务": "AKO_law_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_law_agent")
    assert entry is not None, "AKO_law_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_law_adapter"
    assert entry["invoke_mode"] == "importlib"
    # 语义：active=已上线可调度 / registered=新注册；仅 deprecated 视为未接通
    assert entry["status"] in ("registered", "active"), entry["status"]
    assert entry["source_dir"].endswith("AKO_law_agent")


def test_routing_keywords_target_law():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_callable():
    mod = importlib.import_module("agents.ako_law_adapter")
    assert callable(mod.run)


def test_self_check_real_chain():
    """真实链路：适配器直连 AKOLawAgent 核心 → 自检执行 → 文件落盘 → 三字段。
    注意：自检报告内容（PASS/FAIL）取决于 vault 文件完整性，属环境事实；
    本用例只断言链路成立（error=None + 产出文件 + summary 含"自检"）。"""
    import tempfile

    mod = importlib.import_module("agents.ako_law_adapter")
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="法律自检", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        assert isinstance(result["output_files"], list) and result["output_files"]
        assert Path(result["output_files"][0]).exists()
        assert "自检" in result["summary"]


def test_review_missing_doc_path_error():
    """review 动作缺 doc_path → 协议级兜底 error（不触发 LLM）。"""
    mod = importlib.import_module("agents.ako_law_adapter")
    result = mod.run(intent="合规审查", _hub_output_dir="")
    assert result["error"], "缺 doc_path 应返回 error"
    assert "doc_path" in result["error"]
