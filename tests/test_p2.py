"""
AKO Hub — P2 阶段综合测试
test_p2.py: 验证 sync_monitor、CLI、外部 API。

用法：
    python tests/test_p2.py

前置：P0 初始化已完成（age_hub.db 已建表）
"""

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB
from core.file_bus import FileBus
from core.knowledge_hub import KnowledgeHub
from master.nodes import sync_monitor, standalone_sync_check
from master.state import MasterState
import master.nodes as nodes


def _mock_paths(root: Path):
    nodes._resolve_hub_paths = lambda: {
        "sync_root": str(root),
        "db_path": str(root / "age_hub.db"),
        "chroma_root": str(root / "chroma_db"),
        "file_root": str(root / "files"),
    }


def test_sync_monitor_node():
    print("\n[TEST] sync_monitor 节点")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root)
        file_root = root / "files"
        file_root.mkdir()

        # 创建测试文件
        test_dir = file_root / "taoli" / "docs"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "report.md"
        test_file.write_text("# 测试报告\n", encoding="utf-8")

        # 初始化数据库并注册文件
        db = HubDB(root / "age_hub.db")
        db.connect()
        db.init_schema()
        db.close()

        bus = FileBus(str(root / "age_hub.db"), str(file_root))
        fid = bus.register(
            source_agent="AKO_architect_agent",
            source_node="test",
            rel_path="taoli/docs/report.md",
            file_type="md",
            project_tag="taoli",
            version_tag="v0.1",
            descriptive_name="测试报告",
        )

        # 调用 sync_monitor（通过 MasterState）
        state = MasterState(
            task_id="T-SYNC-001",
            input_payload={"project_tag": "taoli"},
            status="done", generated_files=[], retry_count=0, max_retry=3,
            required_kb_ids=[], output_dir=None, output_summary=None,
            error_log=None, started_at=None, finished_at=None,
            kb_status=None, sync_status=None, spoke_output_paths=[],
        )
        result = sync_monitor(state)

        assert result["sync_status"] == "ok", f"sync_status 非 ok: {result}"
        print(f"  [PASS] 同步状态: {result['sync_status']}")
        print(f"  [PASS] 摘要: {result['sync_summary']}")

        # 验证 sync_log 有记录
        with HubDB(str(root / "age_hub.db")) as db:
            logs = db.fetchall("SELECT * FROM sync_log WHERE file_id=?", (fid,))
        assert len(logs) >= 1
        print(f"  [PASS] sync_log 记录: {len(logs)} 条")

        # 修改文件后再次校验（应触发 mismatch）
        test_file.write_text("# 被修改的内容\n", encoding="utf-8")
        result2 = sync_monitor(state)
        assert result2["sync_status"] == "partial"
        print(f"  [PASS] 修改后校验: {result2['sync_status']}")


def test_standalone_sync():
    print("\n[TEST] standalone_sync_check")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root)
        file_root = root / "files"
        file_root.mkdir()

        # 初始化
        db = HubDB(root / "age_hub.db")
        db.connect()
        db.init_schema()
        db.close()

        # 创建并注册文件
        test_dir = file_root / "common"
        test_dir.mkdir()
        (test_dir / "note.md").write_text("note", encoding="utf-8")

        bus = FileBus(str(root / "age_hub.db"), str(file_root))
        bus.register(
            source_agent="AKO_architect_agent", source_node="test",
            rel_path="common/note.md", file_type="md", project_tag="common",
            version_tag="v0.1", descriptive_name="note",
        )

        # 全量校验
        result = standalone_sync_check()
        assert "sync_summary" in result
        print(f"  [PASS] 全量校验: {result['sync_summary']}")

        # 按项目校验
        result2 = standalone_sync_check(project_tag="common")
        assert result2["sync_results"]["match"] >= 1
        print(f"  [PASS] 按项目校验: match={result2['sync_results']['match']}")


def test_hub_api():
    print("\n[TEST] hub_api 接口")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 创建临时 hub_api 配置
        hub_root = root / "AKO_Hub"
        hub_root.mkdir()
        config_dir = hub_root / "config"
        config_dir.mkdir()
        (config_dir / "hub.yaml").write_text(
            f"sync_root: {hub_root}\n"
            "meta_db: age_hub.db\n"
            "chroma_root: chroma_db\n"
            "file_root: files\n",
            encoding="utf-8",
        )

        # 初始化数据库
        db = HubDB(hub_root / "age_hub.db")
        db.connect()
        db.init_schema()
        db.close()

        kh = KnowledgeHub(str(hub_root / "age_hub.db"), str(hub_root / "chroma_db"))
        kh.register_kb("ako_test", "测试库", "AKO_architect_agent", "taoli", "struct")

        # 临时将 hub_api 指向这个目录
        import hub_api as api
        original_resolve = api._resolve_paths
        api._resolve_paths = lambda: {
            "sync_root": str(hub_root),
            "db_path": str(hub_root / "age_hub.db"),
            "chroma_root": str(hub_root / "chroma_db"),
            "file_root": str(hub_root / "files"),
        }

        try:
            # 测试 hub_status
            status = api.hub_status()
            assert status["knowledge_bases"] >= 1
            print(f"  [PASS] hub_status: KB={status['knowledge_bases']}")

            # 测试 list_knowledge_bases
            kbs = api.list_knowledge_bases()
            assert len(kbs) >= 1
            print(f"  [PASS] list_knowledge_bases: {len(kbs)} 个")

            # 测试 list_files（空库）
            files = api.list_files()
            assert isinstance(files, list)
            print(f"  [PASS] list_files: {len(files)} 个")

        finally:
            api._resolve_paths = original_resolve


if __name__ == "__main__":
    test_sync_monitor_node()
    test_standalone_sync()
    test_hub_api()
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] P2 阶段综合测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
