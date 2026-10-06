# -*- coding: utf-8 -*-
"""批1：architect 接通冒烟——注册条目、路由关键词、适配器 importlib dry-run 链路。"""
import importlib
import os
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "渲染": "AKO_architect_agent",
    "结构计算": "AKO_architect_agent",
    "方案设计": "AKO_architect_agent",
    "建模": "AKO_architect_agent",
    "三维": "AKO_architect_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_architect_agent")
    assert entry is not None, "AKO_architect_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_architect_adapter"
    assert entry["invoke_mode"] == "importlib"
    assert entry["status"] == "registered"
    assert entry["source_dir"].endswith("AKO_architect_agent")


def test_routing_keywords_target_architect():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_and_dryrun_chain():
    """importlib 链路：导入适配器 → run(dry-run) → 三字段 + stage 落盘（无需 architect 依赖）。"""
    mod = importlib.import_module("agents.ako_architect_adapter")
    assert callable(mod.run)

    os.environ["AKO_HUB_SPOKE_DRYRUN"] = "1"
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = mod.run(intent="陶粒墙板节点结构计算", _hub_output_dir=td)
            assert result["error"] is None, result["error"]
            assert isinstance(result["output_files"], list) and result["output_files"]
            stage = Path(result["output_files"][0])
            assert stage.exists() and stage.suffix == ".json"
            assert result["summary"].startswith("architect dry-run OK")
    finally:
        os.environ.pop("AKO_HUB_SPOKE_DRYRUN", None)


def test_adapter_empty_intent_error():
    """空 intent 必须返回 error（协议级兜底）。"""
    mod = importlib.import_module("agents.ako_architect_adapter")
    os.environ["AKO_HUB_SPOKE_DRYRUN"] = "1"
    try:
        result = mod.run(intent="", _hub_output_dir="")
        assert result["error"], "空 intent 应返回 error"
    finally:
        os.environ.pop("AKO_HUB_SPOKE_DRYRUN", None)


def test_adapter_synthesizes_intent_from_wo_fields():
    """intake 老载荷无 intent（只有 action/scope）时由 WO 字段合成，dry-run 可过。"""
    mod = importlib.import_module("agents.ako_architect_adapter")
    os.environ["AKO_HUB_SPOKE_DRYRUN"] = "1"
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = mod.run(intent="", action="方案设计", scope="陶粒墙板厂房", _hub_output_dir=td)
            assert result["error"] is None, result["error"]
            assert result["summary"].startswith("architect dry-run OK")
    finally:
        os.environ.pop("AKO_HUB_SPOKE_DRYRUN", None)
