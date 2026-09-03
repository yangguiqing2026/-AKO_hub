# -*- coding: utf-8 -*-
"""§九 名单清扫固化测试（2026-09-03 批）。

固化项：
1. routing_rules 关键词无重复（历史缺陷：文章×2 → media/writer 后写胜出，已删 media 条）；
2. 文章 → 仅 AKO_writer_agent；
3. 注册表/分类面无中文 id（AKO工作流 已改 AKO_workflow）；
4. 全部已注册 agent workflow 在 agent_names 有中文名（含心跳 *_agent 别名）。
"""
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import list_all_spokes  # noqa: E402
from registry.taxonomy import TAXONOMY  # noqa: E402

NAMES_PATH = PROJECT_ROOT / "config" / "agent_names.yaml"
RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"


def _rules():
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def _names():
    return yaml.safe_load(NAMES_PATH.read_text(encoding="utf-8"))["agents"]


def test_no_duplicate_keywords():
    routes = _rules()["keyword_routes"]
    seen = {}
    for r in routes:
        kw = r["keyword"]
        assert kw not in seen, f"关键词重复: {kw} → {seen[kw]} 与 {r['agent_id']}"
        seen[kw] = r["agent_id"]


def test_wenzhang_routes_writer_only():
    routes = {r["keyword"]: r["agent_id"] for r in _rules()["keyword_routes"]}
    assert routes["文章"] == "AKO_writer_agent"


def test_no_chinese_ids_in_registry_or_taxonomy():
    for s in list_all_spokes():
        assert s["workflow_id"].isascii(), f"注册表含非 ASCII id: {s['workflow_id']}"
    for key in TAXONOMY:
        assert key.isascii(), f"taxonomy 含非 ASCII key: {key}"


def test_all_registered_have_chinese_names():
    names = _names()
    for s in list_all_spokes():
        if s.get("spoke_type") != "agent":
            continue
        wid = s["workflow_id"]
        if wid.startswith("AKO_test_"):  # 既有注册测试的会话内仪器条目，非真实舰队
            continue
        assert wid in names, f"{wid} 缺中文名"
        assert names[wid], f"{wid} 中文名为空"


def test_heartbeat_agent_suffix_aliases_present():
    names = _names()
    for alias in ("AKO_hub_agent", "AKO_identity_service_agent", "AKO_knowledge_agent"):
        assert alias in names and names[alias], f"心跳别名缺中文名: {alias}"
