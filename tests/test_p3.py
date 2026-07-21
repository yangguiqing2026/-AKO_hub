"""
AKO Hub — P3 双机支持测试
test_p3.py: 验证分布式锁、第二台机器初始化、跨机锁冲突。

用法：
    python tests/test_p3.py
"""

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB
from core.distributed_lock import DistributedLock
from core.file_bus import FileBus
from master.state import MasterState
from master.nodes import task_router, workflow_caller, _get_machine_id
from registry import workflows as reg
import master.nodes as nodes


def _mock_paths(root: Path, machine_id: str = "machine_01"):
    nodes._resolve_hub_paths = lambda: {
        "sync_root": str(root),
        "db_path": str(root / "age_hub.db"),
        "chroma_root": str(root / "chroma_db"),
        "file_root": str(root / "files"),
    }
    # 覆盖 _get_machine_id
    nodes._get_machine_id = lambda: machine_id


def test_distributed_lock():
    print("\n[TEST] 分布式锁")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "age_hub.db"
        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.close()

        lock_a = DistributedLock(str(db_path), "machine_01")
        lock_b = DistributedLock(str(db_path), "machine_02")

        # machine_01 获取锁
        assert lock_a.try_acquire(timeout_seconds=60) is True
        print(f"  [PASS] machine_01 获取锁")

        # machine_02 获取失败
        assert lock_b.try_acquire(timeout_seconds=60) is False
        holder = lock_b.is_held()
        assert holder == "machine_01"
        print(f"  [PASS] machine_02 获取失败，持有者={holder}")

        # machine_01 释放
        assert lock_a.release() is True
        print(f"  [PASS] machine_01 释放锁")

        # machine_02 现在可以获取
        assert lock_b.try_acquire(timeout_seconds=60) is True
        print(f"  [PASS] machine_02 获取锁")

        lock_b.release()


def test_task_router_lock_block():
    print("\n[TEST] task_router 锁阻塞")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root, "machine_01")
        db_path = root / "age_hub.db"
        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.close()

        # machine_02 先获取锁
        lock = DistributedLock(str(db_path), "machine_02")
        lock.try_acquire(timeout_seconds=60)

        # machine_01 发起任务，应被阻塞
        state = MasterState(
            task_id="T-LOCK-001", input_payload={"intent": "结构计算"},
            status="pending", required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
        )
        result = task_router(state)
        assert result["status"] == "pending"
        assert "machine_02" in result["error_log"]
        print(f"  [PASS] 锁阻塞: {result['status']}, 提示={result['error_log'][:30]}...")

        lock.release()

        # 释放后恢复正常
        result2 = task_router(state)
        assert result2["status"] == "pending"
        assert "error_log" not in result2 or result2.get("error_log") is None
        print(f"  [PASS] 锁释放后恢复正常: {result2['status']}")


def test_workflow_caller_lock():
    print("\n[TEST] workflow_caller 锁获取失败")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mock_paths(root, "machine_01")
        file_root = root / "files"
        file_root.mkdir()
        db_path = root / "age_hub.db"
        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.close()

        # machine_02 先获取锁
        lock = DistributedLock(str(db_path), "machine_02")
        lock.try_acquire(timeout_seconds=60)

        # machine_01 调用 workflow_caller，应失败
        state = MasterState(
            task_id="T-LOCK-002", target_workflow="wf_ako_architect",
            output_dir="taoli/test", input_payload={"project": "陶粒"},
            required_kb_ids=[], generated_files=[], retry_count=0, max_retry=3,
        )
        result = workflow_caller(state)
        assert result["status"] == "failed"
        assert "machine_02" in result["error_log"]
        print(f"  [PASS] workflow_caller 锁失败: {result['error_log'][:40]}...")

        lock.release()


def test_hub_api_lock():
    print("\n[TEST] hub_api 锁状态接口")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        hub_root = root / "AKO_Hub"
        hub_root.mkdir()
        config_dir = hub_root / "config"
        config_dir.mkdir()
        (config_dir / "hub.yaml").write_text(
            f"sync_root: {hub_root}\n"
            "meta_db: age_hub.db\n"
            "chroma_root: chroma_db\n"
            "file_root: files\n"
            "machine_id: machine_01\n",
            encoding="utf-8",
        )
        db = HubDB(hub_root / "age_hub.db")
        db.connect()
        db.init_schema()
        db.close()

        import hub_api as api
        original_resolve = api._resolve_paths
        api._resolve_paths = lambda: {
            "sync_root": str(hub_root),
            "db_path": str(hub_root / "age_hub.db"),
            "chroma_root": str(hub_root / "chroma_db"),
            "file_root": str(hub_root / "files"),
        }

        try:
            # 初始无锁
            status = api.lock_status()
            assert status["holder"] is None
            print(f"  [PASS] 初始无锁: holder={status['holder']}")

            # 手动获取
            acquire = api.acquire_lock(timeout_seconds=60)
            assert acquire["acquired"] is True
            print(f"  [PASS] 手动获取锁: acquired={acquire['acquired']}")

            # 再次查询
            status2 = api.lock_status()
            assert status2["held_by_self"] is True
            print(f"  [PASS] 锁状态: held_by_self={status2['held_by_self']}")

            # 释放
            release = api.release_lock()
            assert release["released"] is True
            print(f"  [PASS] 手动释放锁: released={release['released']}")

        finally:
            api._resolve_paths = original_resolve


if __name__ == "__main__":
    test_distributed_lock()
    test_task_router_lock_block()
    test_workflow_caller_lock()
    test_hub_api_lock()
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] P3 双机支持测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
