"""
AKO Hub — Master Graph 端到端测试
test_master_graph.py: 验证 task_router → kb_allocator → workflow_caller → file_collector

用法：
    python tests/test_master_graph.py

注意：
  - 本测试不加载真实 LLM/Agent，使用 mock Spoke 验证链路。
  - 需先执行 P0 初始化（scripts/init_hub.py）确保 age_hub.db 已存在。
"""

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from master.graph import build_master_graph
from master.state import MasterState
from core.hub_db import HubDB
from core.knowledge_hub import KnowledgeHub
from core.file_bus import FileBus


def _mock_spoke_module():
    """动态创建一个 mock agent 模块，写入临时目录并加入 sys.path。"""
    tmp = Path(tempfile.mkdtemp())
    mod_dir = tmp / "mock_agents"
    mod_dir.mkdir()

    init_file = mod_dir / "__init__.py"
    init_file.write_text("", encoding="utf-8")

    agent_file = mod_dir / "mock_struct_agent.py"
    agent_file.write_text(
        'def run(**kwargs):\n'
        '    import os\n'
        '    out_dir = kwargs.get("_hub_output_dir", ".")\n'
        '    fpath = os.path.join(out_dir, "mock_report.md")\n'
        '    with open(fpath, "w", encoding="utf-8") as f:\n'
        '        f.write("# Mock 结构报告\\n")\n'
        '    return {"output_files": [fpath], "summary": "mock 完成"}\n',
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp))
    return tmp, "mock_agents.mock_struct_agent"


def test_master_graph_full():
    print("\n[TEST] Master Graph 端到端链路")

    # 1. 准备临时环境
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "age_hub.db"
        chroma_root = root / "chroma_db"
        file_root = root / "files"
        file_root.mkdir()

        # 初始化数据库
        hub_db = HubDB(db_path)
        hub_db.connect()
        hub_db.init_schema()
        hub_db.close()

        # 注册知识库
        kh = KnowledgeHub(str(db_path), str(chroma_root))
        kh.register_kb(
            kb_id="ako_test_struct",
            kb_name="测试结构库",
            agent_name="AKO_architect_agent",
            project_tag="taoli",
            kb_type="struct",
        )

        # 注册 mock Spoke 到 registry（临时覆盖）
        from registry import workflows as reg
        original_registry = reg.SPOKE_REGISTRY.copy()

        tmp_dir, mod_path = _mock_spoke_module()
        reg.SPOKE_REGISTRY.append({
            "workflow_id": "wf_mock_struct",
            "name": "Mock 结构 Agent",
            "spoke_type": "agent",
            "entry_module": mod_path,
            "entry_function": "run",
            "required_kb_ids": ["ako_test_struct"],
            "output_dir": "taoli_wallboard/tech_docs",
            "description": "mock",
            "status": "registered",
        })

        # 临时覆盖配置文件读取
        import master.nodes as nodes
        original_resolve = nodes._resolve_hub_paths
        nodes._resolve_hub_paths = lambda: {
            "sync_root": str(root),
            "db_path": str(db_path),
            "chroma_root": str(chroma_root),
            "file_root": str(file_root),
        }

        try:
            # 2. 构建并运行 Master Graph
            graph = build_master_graph()

            initial_state: MasterState = {
                "task_id": "T-MOCK-001",
                "target_workflow": "",
                "target_agent": None,
                "input_payload": {"workflow_id": "wf_mock_struct", "project": "陶粒"},
                "required_kb_ids": [],
                "output_dir": None,
                "generated_files": [],
                "output_summary": None,
                "status": "pending",
                "error_log": None,
                "retry_count": 0,
                "max_retry": 3,
                "started_at": None,
                "finished_at": None,
                "kb_status": None,
                "sync_status": None,
                "spoke_output_paths": [],
            }

            result = graph.invoke(initial_state)
            result_dict = dict(result)

            assert result_dict["status"] == "done", f"状态非 done: {result_dict['status']}"
            assert result_dict["target_workflow"] == "wf_mock_struct"
            assert result_dict["kb_status"] == "ok"
            assert len(result_dict.get("generated_files", [])) >= 1
            print(f"  [PASS] 全流程状态: {result_dict['status']}")
            print(f"  [PASS] 目标工作流: {result_dict['target_workflow']}")
            print(f"  [PASS] 知识库状态: {result_dict['kb_status']}")
            print(f"  [PASS] 注册文件数: {len(result_dict['generated_files'])}")
            print(f"  [PASS] 输出摘要: {result_dict.get('output_summary', '')}")

        finally:
            # 恢复
            reg.SPOKE_REGISTRY = original_registry
            nodes._resolve_hub_paths = original_resolve
            sys.path.remove(str(tmp_dir))

    print("\n[ALL PASS] Master Graph 端到端测试通过")


if __name__ == "__main__":
    test_master_graph_full()
