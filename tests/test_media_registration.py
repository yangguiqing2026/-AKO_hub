# -*- coding: utf-8 -*-
"""批1：media 接通冒烟——注册条目、路由关键词、适配器导入。

口径：真实 analysis 链已人工探针验证一次（2026-09-03，含 LLM gap_analyzer，
见 logs/batch1_media_acceptance_2026-09-03.md 证据）；因每次 analysis 会调
deepseek-chat 且写入 media 仓库自身数据库，不入自动化测试循环。
注：routing 中"文章"关键词存在 media/writer 重复冲突（后写 writer 胜出），
本用例只断言无冲突关键词"文案"，冲突项记录入 §九 名单清扫队列。
"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_media_agent")
    assert entry is not None, "AKO_media_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_media_adapter"
    assert entry["invoke_mode"] == "importlib"
    assert entry["status"] in ("registered", "active"), entry["status"]
    assert entry["source_dir"].endswith("AKO_media_agent")


def test_routing_keyword_wenan_targets_media():
    """无冲突关键词 文案 → AKO_media_agent。"""
    routes = _load_keyword_routes()
    assert routes.get("文案") == "AKO_media_agent"


def test_adapter_import_callable():
    mod = importlib.import_module("agents.ako_media_adapter")
    assert callable(mod.run)
