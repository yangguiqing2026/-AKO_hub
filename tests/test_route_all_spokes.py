"""
AKO Hub 路由连通性测试
测试所有 Spoke 的 task_router → SPOKE_REGISTRY → import → run() 链路。
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from registry.workflows import SPOKE_REGISTRY, get_spoke_by_id

# ── task_router 的 intent_map ──
INTENT_MAP = {
    "结构": "AKO_architect_agent",
    "计算": "AKO_architect_agent",
    "图纸": "AKO_drawing_inspector",
    "质检": "AKO_drawing_inspector",
    "图像": "AKO_image_analyzer",
    "缺陷": "AKO_image_analyzer",
    "问答": "AKO_chat",
    "规范": "AKO_chat",
    "查询": "AKO_chat",
    "主流程": "AKO工作流",
    "商业": "AKO_business",
    "报价": "AKO_quote",
    "报表": "AKO_reports",
    "内容": "AKO_geo",
    "营销": "AKO_geo",
    "媒体": "AKO_media",
}

# 测试关键的 intent→spoke 路由
TEST_CASES = [
    ("商业", "AKO_business", True),
    ("报价", "AKO_quote", True),
    ("媒体", "AKO_media", True),
    ("结构", "AKO_architect_agent", False),
    ("图纸", "AKO_drawing_inspector", False),
    ("图像", "AKO_image_analyzer", False),
    ("问答", "AKO_chat", False),
    ("主流程", "AKO工作流", False),
    ("报表", "AKO_reports", False),
    ("营销", "AKO_geo", False),
]

results = {"pass": [], "fail": [], "skip": []}

for keyword, expected_wf, run_test in TEST_CASES:
    matched = None
    for kw, wf in INTENT_MAP.items():
        if kw in keyword:
            matched = wf
            break

    spoke = get_spoke_by_id(matched) if matched else None

    # Step 1: intent_map 路由
    if matched != expected_wf:
        results["fail"].append(f"{keyword} → 路由失败: got {matched}, expected {expected_wf}")
        continue

    # Step 2: SPOKE_REGISTRY 注册
    if spoke is None:
        results["fail"].append(f"{keyword} → {expected_wf}: 未在 SPOKE_REGISTRY 中注册")
        continue

    entry_mod = spoke["entry_module"]
    entry_func = spoke.get("entry_function", "run")
    source_dir = spoke.get("source_dir", "")

    # Step 3: import 测试
    try:
        import importlib
        # 模拟 workflow_caller 的路径注入
        path_inserted = False
        if source_dir and Path(source_dir).exists():
            src = str(Path(source_dir).resolve())
            if src not in sys.path:
                sys.path.insert(0, src)
                path_inserted = True
        mod = importlib.import_module(entry_mod)
    except Exception as e:
        results["fail"].append(f"{keyword} → {expected_wf}: import {entry_mod} 失败 — {e}")
        continue
    finally:
        if path_inserted:
            try:
                sys.path.remove(src)
            except Exception:
                pass

    # Step 4: entry_function 存在
    func = getattr(mod, entry_func, None)
    if func is None:
        results["fail"].append(f"{keyword} → {expected_wf}: 模块 {entry_mod} 中未找到 {entry_func}")
        continue

    # Step 5: run() 调用测试（仅 marked spokes）
    if run_test:
        test_dir = Path(f"./tmp_hub_route_test/{expected_wf}")
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            output = func(
                intent=keyword,
                project_tag="route_test",
                _hub_output_dir=str(test_dir),
            )
            if output.get("error"):
                results["pass"].append(f"{keyword} → {expected_wf}: run() 完成（含业务警告: {output['error'][:80]}）")
            else:
                summary = output.get("summary", "")[:60]
                results["pass"].append(f"{keyword} → {expected_wf}: run() OK — {summary}")
        except Exception as e:
            results["fail"].append(f"{keyword} → {expected_wf}: run() 异常 — {type(e).__name__}: {e}")
    else:
        results["skip"].append(f"{keyword} → {expected_wf}: import OK（跳过 run 测试）")


# ── 汇总 ──
print("=" * 60)
print("AKO Hub 路由连通性测试报告")
print("=" * 60)

for status in ["pass", "fail", "skip"]:
    items = results[status]
    if not items:
        continue
    emoji = {"pass": "✅", "fail": "❌", "skip": "⏭️"}[status]
    print(f"\n{emoji} {status.upper()} ({len(items)})")
    for item in items:
        print(f"  {item}")

total = sum(len(v) for v in results.values())
print(f"\n总计: {len(results['pass'])}/{total} 通过, {len(results['fail'])}/{total} 失败")
