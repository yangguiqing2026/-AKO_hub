# -*- coding: utf-8 -*-
"""批3 L0 注册级测试（2026-09-03 口径：运维/治理层 supervisor 常驻服务与治理工具）。

13 个：registry/audit/qc/guardian/monitor/identity_service_agent（supervisor 常驻）
+ clinic/devil/cluster_guardian/config_audit/evolution/dependency_map/kb_agent。
固化：全部 manual_gui 注册、taxonomy 分类齐、禁 hub 调度（与批2 L0 同护栏）。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402
from registry.taxonomy import TAXONOMY  # noqa: E402

L0_IDS = [
    "AKO_registry_agent", "AKO_audit_agent", "AKO_qc_agent",
    "AKO_guardian_agent", "AKO_monitor_agent", "AKO_identity_service_agent",
    "AKO_clinic_agent", "AKO_devil_agent", "AKO_cluster_guardian_agent",
    "AKO_config_audit_agent", "AKO_evolution_agent",
    "AKO_dependency_map_agent", "AKO_kb_agent",
]


def test_batch3_all_registered_manual_gui():
    for wid in L0_IDS:
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册"
        assert entry["invoke_mode"] == "manual_gui", f"{wid}: {entry['invoke_mode']}"
        assert entry["status"] == "registered", wid
        t = TAXONOMY.get(wid, {})
        assert t.get("domain") and t.get("function"), f"{wid} 缺 taxonomy"


def test_batch3_no_keywords_routed():
    """批3 治理/运维实体不应出现在 NL 关键词路由表。"""
    import yaml

    rules = yaml.safe_load(
        (PROJECT_ROOT / "config" / "routing_rules.yaml").read_text(encoding="utf-8")
    )["keyword_routes"]
    routed = {r["agent_id"] for r in rules}
    overlap = routed & set(L0_IDS)
    assert not overlap, f"批3 L0 实体不应被 NL 路由: {overlap}"
