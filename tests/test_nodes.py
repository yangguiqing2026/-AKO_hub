"""
AKO Hub — Master Graph 节点单元测试
test_nodes.py: 不依赖 langgraph，仅测试 nodes.py 中各节点函数逻辑。

用法：
    python tests/test_nodes.py
"""

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from master.state import MasterState
from master.nodes import task_router, kb_allocator, workflow_caller, file_collector, error_handler, state_aggregator
from core.hub_db import HubDB
from core.knowledge_hub import KnowledgeHub
from core.file_bus import FileBus
from registry import workflows as reg


def _mock_paths(root: Path):
    """覆盖 nodes.py 的路径解析。"""
    import master.nodes as nodes
    nodes._resolve_hub_paths = lambda: {
        "sync_root": str(root),
        "db_path": str(root / "age_hub.db"),
        "chroma_root": str(root / "chroma_db"),
        "file_root": str(root / "files"),
    }


def test_task_router():
    print("\n[TEST] task_router")

    # 显式 workflow_id
    state = MasterState(
        task_id="T-001", input_payload={"workflow_id": "AKO_architect_agent"},
        status="pending", required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
    )
    result = task_router(state)
    assert result["target_workflow"] == "AKO_architect_agent"
    assert result["status"] == "pending"
    print(f"  [PASS] 显式指定: {result['target_workflow']}")

    # 关键词路由
    state = MasterState(
        task_id="T-002", input_payload={"intent": "帮我做结构计算"},
        status="pending", required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
    )
    result = task_router(state)
    assert result["target_workflow"] == "AKO_architect_agent"
    print(f"  [PASS] 关键词路由: {result['target_workflow']}")

    # 图纸质检
    state = MasterState(
        task_id="T-003", input_payload={"intent": "图纸质检"},
        status="pending", required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
    )
    result = task_router(state)
    assert result["target_workflow"] == "AKO_drawing_inspector"
    print(f"  [PASS] 质检路由: {result['target_workflow']}")

    # 无效意图
    state = MasterState(
        task_id="T-004", input_payload={"intent": "随便问问"},
        status="pending", required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
    )
    result = task_router(state)
    assert result["status"] == "failed"
    print(f"  [PASS] 无效意图: {result['status']}")


def test_kb_allocator():
    print("\n[TEST] kb_allocator")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root)
        db_path = root / "age_hub.db"
        chroma_root = root / "chroma"

        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.close()
        kh = KnowledgeHub(str(db_path), str(chroma_root))
        kh.register_kb("ako_test_kb", "测试库", "AKO_architect_agent", "taoli", "struct")

        # 知识库存在
        state = MasterState(
            task_id="T-005", required_kb_ids=["ako_test_kb"],
            status="pending", input_payload={}, generated_files=[], retry_count=0, max_retry=3,
        )
        result = kb_allocator(state)
        assert result["kb_status"] == "ok"
        print(f"  [PASS] 知识库存在: {result['kb_status']}")

        # 知识库缺失
        state = MasterState(
            task_id="T-006", required_kb_ids=["ako_missing"],
            status="pending", input_payload={}, generated_files=[], retry_count=0, max_retry=3,
        )
        result = kb_allocator(state)
        assert result["kb_status"] == "missing"
        print(f"  [PASS] 知识库缺失: {result['kb_status']}")


def test_workflow_caller_and_file_collector():
    print("\n[TEST] workflow_caller + file_collector")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root)
        file_root = root / "files"
        file_root.mkdir()

        # 创建 mock agent 模块
        mock_dir = root / "mock_agents"
        mock_dir.mkdir()
        (mock_dir / "__init__.py").write_text("", encoding="utf-8")
        (mock_dir / "mock_agent.py").write_text(
            'def run(**kwargs):\n'
            '    import os\n'
            '    out = kwargs.get("_hub_output_dir", ".")\n'
            '    f = os.path.join(out, "report.md")\n'
            '    with open(f, "w", encoding="utf-8") as fh:\n'
            '        fh.write("# Mock Report\\n")\n'
            '    return {"output_files": [f], "summary": "mock done"}\n',
            encoding="utf-8",
        )
        sys.path.insert(0, str(root))

        # 临时注册 mock Spoke
        original = reg.SPOKE_REGISTRY.copy()
        reg.SPOKE_REGISTRY.append({
            "workflow_id": "wf_mock_test",
            "name": "Mock Agent",
            "spoke_type": "agent",
            "entry_module": "mock_agents.mock_agent",
            "entry_function": "run",
            "required_kb_ids": [],
            "output_dir": "taoli/test",
            "description": "",
            "status": "registered",
        })

        try:
            # workflow_caller
            state = MasterState(
                task_id="T-007", target_workflow="wf_mock_test", output_dir="taoli/test",
                input_payload={"project": "陶粒"}, required_kb_ids=[],
                generated_files=[], retry_count=0, max_retry=3,
            )
            result = workflow_caller(state)
            assert result["status"] != "failed"
            assert len(result["spoke_output_paths"]) >= 1
            print(f"  [PASS] workflow_caller: {result['status']}, 文件数={len(result['spoke_output_paths'])}")

            # file_collector
            state.update(result)
            result2 = file_collector(state)
            assert len(result2["generated_files"]) >= 1
            print(f"  [PASS] file_collector: 注册 {len(result2['generated_files'])} 个文件")

        finally:
            reg.SPOKE_REGISTRY = original
            sys.path.remove(str(root))


def test_error_and_aggregator():
    print("\n[TEST] error_handler + state_aggregator")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root)
        db = HubDB(root / "age_hub.db")
        db.connect()
        db.init_schema()
        db.close()

        # error_handler（retry_count 已达上限，应返回最终失败）
        state = MasterState(
            task_id="T-008", status="failed", error_log="测试错误", retry_count=3, max_retry=3,
            input_payload={}, required_kb_ids=[], generated_files=[],
        )
        result = error_handler(state)
        assert result["status"] == "failed"
        print(f"  [PASS] error_handler: {result['status']}")

        # state_aggregator
        state = MasterState(
            task_id="T-009", status="running", generated_files=["F-001"],
            spoke_output={"summary": "done"}, retry_count=0, max_retry=3,
            input_payload={}, required_kb_ids=[],
        )
        result = state_aggregator(state)
        assert result["status"] == "done"
        assert result["output_summary"] == "done"
        print(f"  [PASS] state_aggregator: {result['status']}, summary={result['output_summary']}")


if __name__ == "__main__":
    test_task_router()
    test_kb_allocator()
    test_workflow_caller_and_file_collector()
    test_error_and_aggregator()
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] Master Graph 节点单元测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
