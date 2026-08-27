"""
AKO Hub — hub_api 分类学集成测试
test_hub_api_taxonomy.py: 全部已注册 workflow 均须在 TAXONOMY 有分类；
register_spoke_api 的分类落库可见；非法分类返回 classification_saved=False。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import list_all_spokes, unregister_spoke
from registry.taxonomy import TAXONOMY, get_domain, get_function
from hub_api import register_spoke_api


def test_all_registered_workflows_classified():
    """16 个已注册 workflow_id 全部在 TAXONOMY 有 domain+function。"""
    ids = [s["workflow_id"] for s in list_all_spokes()]
    assert ids, "注册表为空"
    missing = []
    for wid in ids:
        t = TAXONOMY.get(wid, {})
        if not t.get("domain") or not t.get("function"):
            missing.append(wid)
    assert not missing, f"未分类 workflow: {missing}"
    print(f"  [PASS] {len(ids)} 个已注册 workflow 全部分类齐全")


def test_register_spoke_api_classification_saved():
    """注册时传合法 domain/function → classification_saved=True 且查询可见。"""
    result = register_spoke_api(
        workflow_id="AKO_test_taxonomy_wf",
        name="测试分类落库",
        spoke_type="agent",
        entry_module="agents.ako_chat_adapter",
        source_dir=str(Path(__file__).resolve().parent.parent),
        domain="ops",
        function="monitor",
    )
    assert result["registered"] is True
    assert result["classification_saved"] is True
    assert get_domain("AKO_test_taxonomy_wf") == "ops"
    assert get_function("AKO_test_taxonomy_wf") == "monitor"
    print("  [PASS] register_spoke_api 分类落库可见")


def test_register_spoke_api_invalid_classification():
    """非法 domain → classification_saved=False，分类不落库。"""
    result = register_spoke_api(
        workflow_id="AKO_test_taxonomy_bad",
        name="非法分类测试",
        spoke_type="agent",
        entry_module="agents.ako_chat_adapter",
        source_dir=str(Path(__file__).resolve().parent.parent),
        domain="bad_domain",
        function="monitor",
    )
    assert result["classification_saved"] is False
    assert get_domain("AKO_test_taxonomy_bad") == ""
    print("  [PASS] 非法分类拒绝落库")


def _cleanup():
    for wid in ("AKO_test_taxonomy_wf", "AKO_test_taxonomy_bad"):
        unregister_spoke(wid)
        TAXONOMY.pop(wid, None)


if __name__ == "__main__":
    try:
        test_all_registered_workflows_classified()
        test_register_spoke_api_classification_saved()
        test_register_spoke_api_invalid_classification()
    finally:
        _cleanup()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] hub_api taxonomy 集成测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
