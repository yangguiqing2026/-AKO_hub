"""验证三个 Agent 适配器导入和注册状态"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def main():
    errors = []

    # 1. 验证适配器模块导入
    print("=== 验证 Agent 适配器导入 ===")
    try:
        from agents.ako_architect_adapter import run as run_architect
        print("  [OK] ako_architect_adapter 导入成功")
    except Exception as e:
        print(f"  [FAIL] ako_architect_adapter: {e}")
        errors.append(str(e))

    try:
        from agents.ako_drawing_inspector import run as run_inspector
        print("  [OK] ako_drawing_inspector 导入成功")
    except Exception as e:
        print(f"  [FAIL] ako_drawing_inspector: {e}")
        errors.append(str(e))

    try:
        from agents.ako_image_analyzer import run as run_analyzer
        print("  [OK] ako_image_analyzer 导入成功")
    except Exception as e:
        print(f"  [FAIL] ako_image_analyzer: {e}")
        errors.append(str(e))

    # 2. 验证注册表状态
    print("\n=== 验证注册表状态 ===")
    from registry.workflows import SPOKE_REGISTRY, list_spokes_by_type
    agents = list_spokes_by_type("agent")
    workflows = list_spokes_by_type("workflow")
    print(f"  注册表总计: {len(SPOKE_REGISTRY)} 条目")
    print(f"  Agent: {len(agents)} 个")
    print(f"  Workflow: {len(workflows)} 个")
    for a in agents:
        print(f"    - {a['workflow_id']}: {a['name']} (模块: {a['entry_module']}, 状态: {a['status']})")

    # 3. 验证适配器 run() 函数可用
    import tempfile, json
    print("\n=== 验证适配器 run() 函数 ===")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "outputs"
        result = run_architect(intent="结构计算", project_tag="taoli", _hub_output_dir=str(out))
        print(f"  run_architect() 返回: {result.get('summary')[:60]}...")
        assert isinstance(result, dict), "返回类型应为 dict"
        assert "output_files" in result, "应包含 output_files"
        assert "summary" in result, "应包含 summary"

        # 清理
        import shutil
        shutil.rmtree(str(out), ignore_errors=True)

    print("\n=== 全部验证通过 ===")
    return 0 if not errors else 1

if __name__ == "__main__":
    sys.exit(main())