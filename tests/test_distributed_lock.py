"""
AKO Hub — 分布式锁单元测试
test_distributed_lock.py: 覆盖 acquire/release/is_held 与跨 machine_id 冲突。
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.distributed_lock import DistributedLock


def test_acquire_release_held():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "age_hub.db")
        lock = DistributedLock(db, "machine_A")
        assert lock.is_held() is None
        assert lock.try_acquire(timeout_seconds=60) is True
        assert lock.is_held() == "machine_A"
        assert lock.is_held_by_self() is True
        assert lock.release() is True
        assert lock.is_held() is None
        print("  [PASS] acquire/release/is_held")


def test_cross_machine_conflict():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "age_hub.db")
        a = DistributedLock(db, "machine_A")
        b = DistributedLock(db, "machine_B")
        assert a.try_acquire(timeout_seconds=60) is True
        # 另一台机器在锁未过期时无法获取
        assert b.try_acquire(timeout_seconds=60) is False
        # 原持有者仍持有
        assert a.is_held() == "machine_A"
        # 释放后另一台机器可获取
        assert a.release() is True
        assert b.try_acquire(timeout_seconds=60) is True
        assert b.is_held() == "machine_B"
        assert b.release() is True
        print("  [PASS] 跨 machine_id 互斥")


def test_force_release_and_expiry():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "age_hub.db")
        a = DistributedLock(db, "machine_A")
        b = DistributedLock(db, "machine_B")
        assert a.try_acquire(timeout_seconds=60) is True
        assert b.force_release() is True
        assert a.is_held() is None
        # 过期锁可被清理后重新获取（1 秒超时）
        assert a.try_acquire(timeout_seconds=1) is True
        import time
        time.sleep(1.2)
        assert b.try_acquire(timeout_seconds=60) is True
        print("  [PASS] force_release + 过期清理")


if __name__ == "__main__":
    test_acquire_release_held()
    test_cross_machine_conflict()
    test_force_release_and_expiry()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] distributed_lock 单元测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
