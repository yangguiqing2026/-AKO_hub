"""
AKO Hub — taxonomy 分类学单元测试
test_taxonomy.py: 覆盖三维枚举、查询辅助与 set_classification（合法/非法值）。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.taxonomy import (
    VALID_DOMAINS, VALID_FUNCTIONS, UNCLASSIFIED,
    get_domain, get_function, get_category,
    list_by_domain, list_by_function,
    find_unclassified, set_classification,
    is_valid_domain, is_valid_function,
)


def test_enums_well_formed():
    """枚举必须非空且不含空字符串。"""
    assert VALID_DOMAINS and VALID_FUNCTIONS
    assert "" not in VALID_DOMAINS and "" not in VALID_FUNCTIONS
    print("  [PASS] 枚举结构完整")


def test_get_domain_function():
    """权威映射的查询与未分类占位。"""
    assert get_domain("AKO_law_agent") == "governance"
    assert get_function("AKO_law_agent") == "analyzer"
    assert get_domain("AKO_hub") == "infrastructure"
    assert get_function("AKO_netwatch_agent") == "monitor"
    assert get_domain("AKO_不存在") == UNCLASSIFIED
    assert get_function("AKO_不存在") == UNCLASSIFIED
    print("  [PASS] get_domain/get_function")


def test_list_by_helpers():
    """list_by_domain / list_by_function 返回子集关系正确。"""
    eng = list_by_domain("engineering")
    assert "AKO_architect_agent" in eng
    assert "AKO_law_agent" not in eng
    mon = list_by_function("monitor")
    assert "AKO_netwatch_agent" in mon
    print("  [PASS] list_by_domain/list_by_function")


def test_find_unclassified():
    """未分类探测：注册了但不在 TAXONOMY 的条目必须被报告。"""
    result = find_unclassified(registered_ids=["AKO_ghost_agent"])
    assert "AKO_ghost_agent" in result
    assert "AKO_law_agent" not in result
    print("  [PASS] find_unclassified")


def test_set_classification():
    """set_classification 合法/非法值行为。"""
    # 合法：写入并返回 True
    assert set_classification("AKO_test_wf", "ops", "monitor") is True
    assert get_domain("AKO_test_wf") == "ops"
    assert get_function("AKO_test_wf") == "monitor"
    # 幂等：重复登记同值仍 True
    assert set_classification("AKO_test_wf", "ops", "monitor") is True
    # 非法 domain/function/空 id：返回 False 且不写入
    assert set_classification("AKO_test_wf2", "bad_domain", "monitor") is False
    assert set_classification("AKO_test_wf2", "ops", "bad_function") is False
    assert set_classification("", "ops", "monitor") is False
    assert get_domain("AKO_test_wf2") == UNCLASSIFIED
    # 清理测试残留
    from registry.taxonomy import TAXONOMY
    TAXONOMY.pop("AKO_test_wf", None)
    print("  [PASS] set_classification 合法/非法")


if __name__ == "__main__":
    test_enums_well_formed()
    test_get_domain_function()
    test_list_by_helpers()
    test_find_unclassified()
    test_set_classification()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] taxonomy 单元测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
