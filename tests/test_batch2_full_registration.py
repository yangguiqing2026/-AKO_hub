# -*- coding: utf-8 -*-
"""批2 全接通：standard / client_profile（纯本地规则链，零成本可真实调度）。

断言：注册条目完整、路由关键词命中、适配器导入 + 真实链路（demo 参数落盘三字段）。
"""
import importlib
import sys
import tempfile
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"

AGENTS = {
    "AKO_standard_agent": ("agents.ako_standard_adapter", ["企业标准", "标准起草"]),
    "AKO_client_profile_agent": ("agents.ako_client_profile_adapter", ["客户画像", "画像"]),
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_registry_entries_complete():
    for wid, (module, _kw) in AGENTS.items():
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册"
        assert entry["entry_module"] == module, wid
        assert entry["invoke_mode"] == "importlib", wid
        assert entry["status"] in ("registered", "active"), wid


def test_routing_keywords():
    routes = _load_keyword_routes()
    for wid, (_module, keywords) in AGENTS.items():
        for kw in keywords:
            assert routes.get(kw) == wid, f"{kw} 未路由到 {wid}"


def test_standard_real_chain():
    """standard 真实链（模板渲染零成本）：demo 参数 → md 起草 + 合规报告。"""
    mod = importlib.import_module("agents.ako_standard_adapter")
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="起草企业标准", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        assert result["output_files"], "无产出"
        exts = {Path(f).suffix for f in result["output_files"]}
        assert ".md" in exts, exts
        assert "置信度" in result["summary"], result["summary"]


def test_client_profile_real_chain():
    """client_profile 真实链（纯规则零成本）：demo 输入 → 画像 JSON + 行动矩阵 JSON。"""
    mod = importlib.import_module("agents.ako_client_profile_adapter")
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="客户画像", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        names = {Path(f).name for f in result["output_files"]}
        assert any(n.endswith("_profile.json") for n in names), names
        assert any(n.endswith("_action_matrix.json") for n in names), names
        assert "客户画像完成" in result["summary"], result["summary"]
