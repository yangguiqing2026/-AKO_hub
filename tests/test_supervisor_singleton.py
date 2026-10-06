"""
AKO Hub — agent_supervisor 单实例锁单元测试

test_supervisor_singleton.py：覆盖 pid 锁的原子接管语义。

背景（2026-09-11）：原 _acquire_singleton 用「先读后写」（exists → read →
write_text）。**这是一处潜在竞态，本机未观测到实际触发** —— 因为 supervisor
目前只有 start_agents.ps1 一个入口，且其自带文件锁。但入口不止一个（开机计划
任务、start_all.ps1、手工），去掉那道文件锁即会暴露：两个进程同时启动时会双双
读到陈旧/空缺状态、双双写入、双双返回 True，各自拉起一套受管服务，而 Windows
允许两个进程 bind 同一端口而不报错，故障因此静默。

修复以 O_CREAT|O_EXCL 原子独占创建为唯一裁决点：读到的锁只用于判断「是否
需要清除陈旧锁」，绝不作为持锁依据。本文件的核心是 test_try_create_lock_*，
它直接锁死这一原子性属性——退化回「先读后写」即会失败。

用法：
    python -m pytest tests/test_supervisor_singleton.py -v
"""

import os
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import agent_supervisor as sup


@pytest.fixture()
def lock_path(tmp_path, monkeypatch):
    """把锁文件重定向到临时目录（monkeypatch 自动还原，避免污染 logs/）。"""
    path = tmp_path / "supervisor.lck"
    monkeypatch.setattr(sup, "SUPERVISOR_LOCK", path)
    return path


# ── 原子性：修复的根因，核心回归测试 ──────────────────────────────


def test_try_create_lock_is_atomic_under_threads(lock_path):
    """N 个线程同时抢建锁文件，恰好一个成功。

    这是对「先读后写」竞态的直接回归：若实现退化为「exists 检查 + write_text」，
    多个线程会同时通过检查而全部成功，断言 len(winners) == 1 立刻失败。
    """
    n = 24
    barrier = threading.Barrier(n)
    winners: list[int] = []
    guard = threading.Lock()

    def worker(idx: int) -> None:
        barrier.wait()  # 尽量让所有线程同时发起
        if sup._try_create_lock():
            with guard:
                winners.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1, f"应恰有 1 个线程持锁，实际 {len(winners)} 个"
    assert lock_path.exists()


def test_try_create_lock_writes_own_pid(lock_path):
    assert sup._try_create_lock() is True
    assert int(lock_path.read_text(encoding="utf-8").strip()) == os.getpid()


def test_try_create_lock_creates_parent_dir(tmp_path, monkeypatch):
    """logs/ 不存在时也应能建锁（开机自启时目录可能尚未创建）。"""
    nested = tmp_path / "not" / "yet" / "supervisor.lck"
    monkeypatch.setattr(sup, "SUPERVISOR_LOCK", nested)
    assert sup._try_create_lock() is True
    assert nested.exists()


def test_try_create_lock_fails_when_held(lock_path):
    assert sup._try_create_lock() is True
    assert sup._try_create_lock() is False


# ── 接管语义：活实例在位则让位，陈旧锁则接管 ──────────────────────


def test_acquire_succeeds_when_no_lock(lock_path):
    assert sup._acquire_singleton() is True
    assert int(lock_path.read_text(encoding="utf-8").strip()) == os.getpid()


def test_acquire_blocked_by_live_instance(lock_path, monkeypatch):
    """另一活 supervisor 持锁 → 让位（返回 False），且不改写锁文件。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(sup, "_is_live_supervisor", lambda pid: True)

    assert sup._acquire_singleton() is False
    assert lock_path.read_text(encoding="utf-8").strip() == "999999"


def test_acquire_takes_over_stale_lock(lock_path, monkeypatch):
    """陈旧锁（pid 已死）→ 清除并接管。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(sup, "_is_live_supervisor", lambda pid: False)

    assert sup._acquire_singleton() is True
    assert int(lock_path.read_text(encoding="utf-8").strip()) == os.getpid()


def test_acquire_takes_over_corrupt_lock(lock_path):
    """锁内容损坏（非数字）→ 视作陈旧并接管，不能永久卡死自启。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("not-a-pid", encoding="utf-8")

    assert sup._acquire_singleton() is True
    assert int(lock_path.read_text(encoding="utf-8").strip()) == os.getpid()


def test_acquire_takes_over_empty_lock(lock_path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("", encoding="utf-8")
    assert sup._acquire_singleton() is True


# ── 释放：只释放自己的锁 ─────────────────────────────────────────


def test_release_removes_own_lock(lock_path):
    assert sup._acquire_singleton() is True
    sup._release_singleton()
    assert not lock_path.exists()


def test_release_leaves_foreign_lock(lock_path):
    """锁属于别的 pid 时不得删除（防误清活实例的锁 → 引出第三个实例）。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999", encoding="utf-8")
    sup._release_singleton()
    assert lock_path.exists()
    assert lock_path.read_text(encoding="utf-8").strip() == "999999"


def test_release_when_no_lock_is_noop(lock_path):
    sup._release_singleton()  # 不抛异常即可
    assert not lock_path.exists()


def test_acquire_release_acquire_roundtrip(lock_path):
    """释放后可被再次接管（正常重启路径）。"""
    assert sup._acquire_singleton() is True
    sup._release_singleton()
    assert sup._acquire_singleton() is True
