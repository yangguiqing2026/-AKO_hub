"""
AKO Hub — hub 本体单实例锁判定单元测试

背景（2026-09-14 双实例事故）：app.py 的单实例锁存在判定漏洞。_is_live_hub()
要求进程命令行同时含 "app.py" 与 "AKO_hub"，但进程 CommandLine **不含工作目录**
—— intake 侧 hub_bootstrap.launch_hub() 用 cwd=D:\\AKO\\AKO_hub + 相对 "app.py"
拉起，命令行只有 "pythonw.exe app.py"，对锁完全不可见。

后果：新实例启动时判定「无活 hub」，直接接管 logs/hub.lck 并与旧实例并存。
Windows 允许两个进程 bind 同一端口而不报错，故障静默 —— 现场实测两个 PID
同时 LISTEN :8080 与 :5000，双 pending_worker 竞争消费同一 task_queue，
同批代码修复可能被未重启的旧实例用旧模块执行。

本文件锁死的不变量：**只要进程确实是 hub 目录下的 app.py，无论命令行写的是
绝对路径还是相对路径，_is_live_hub() 都必须认出它。**

用法：
    python -m pytest tests/test_hub_singleton.py -v
"""

import sys
from pathlib import Path

import psutil
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app as hub_app


class _FakeProc:
    """可控的 psutil.Process 替身。exc 非空时所有探测抛异常（模拟进程消失）。"""

    def __init__(self, cmdline=None, cwd=None, exc=None):
        self._cmdline = cmdline or []
        self._cwd = cwd
        self._exc = exc

    def cmdline(self):
        if self._exc is not None:
            raise self._exc
        return self._cmdline

    def cwd(self):
        if self._exc is not None:
            raise self._exc
        if self._cwd is None:
            raise psutil.AccessDenied()
        return self._cwd


@pytest.fixture()
def hub_dir(tmp_path, monkeypatch):
    """把 hub 目录重定向到临时目录，避免依赖本机真实安装路径。"""
    monkeypatch.setattr(hub_app, "HUB_DIR", tmp_path)
    return tmp_path


def _patch_proc(monkeypatch, proc):
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)


# ── 回归核心：相对路径启动的 hub 必须被认出（2026-09-14 事故根因） ──


def test_relative_cmdline_recognized_via_cwd(hub_dir, monkeypatch) -> None:
    """命令行只有相对 app.py 时，凭工作目录仍须认出（hub_bootstrap 的启动形态）。

    这是事故的直接回归：修复前 cmdline "pythonw.exe app.py" 不含 AKO_hub，
    _is_live_hub 返回 False → 锁形同虚设 → 双实例并存。
    """
    _patch_proc(monkeypatch, _FakeProc(cmdline=["pythonw.exe", "app.py"], cwd=str(hub_dir)))
    assert hub_app._is_live_hub(4242) is True


def test_relative_cmdline_case_insensitive_cwd(hub_dir, monkeypatch) -> None:
    """Windows 路径大小写不敏感，cwd 大小写不同仍须认出。"""
    _patch_proc(monkeypatch, _FakeProc(cmdline=["pythonw.exe", "app.py"], cwd=str(hub_dir).upper()))
    assert hub_app._is_live_hub(4242) is True


# ── 原有判定不得退化：绝对路径命令行 ──────────────────────────────


def test_absolute_cmdline_still_recognized(hub_dir, monkeypatch) -> None:
    _patch_proc(monkeypatch, _FakeProc(cmdline=[r"D:\AKO\AKO_hub\app.py"]))
    assert hub_app._is_live_hub(4242) is True


# ── 不得误判：非 hub 进程与已死进程 ────────────────────────────────


def test_relative_cmdline_from_other_cwd_rejected(hub_dir, monkeypatch) -> None:
    """别的目录下也有 app.py（如 intake 的 app.py），不得误认作 hub。"""
    _patch_proc(monkeypatch, _FakeProc(cmdline=["python.exe", "app.py"], cwd=str(hub_dir.parent / "other")))
    assert hub_app._is_live_hub(4242) is False


def test_cwd_unavailable_rejected(hub_dir, monkeypatch) -> None:
    """cwd 取不到（权限不足）时保守判否，不得抛异常。"""
    _patch_proc(monkeypatch, _FakeProc(cmdline=["pythonw.exe", "app.py"], cwd=None))
    assert hub_app._is_live_hub(4242) is False


def test_dead_pid_rejected(hub_dir, monkeypatch) -> None:
    _patch_proc(monkeypatch, _FakeProc(exc=psutil.NoSuchProcess(4242)))
    assert hub_app._is_live_hub(4242) is False


def test_unrelated_process_rejected(hub_dir, monkeypatch) -> None:
    _patch_proc(monkeypatch, _FakeProc(cmdline=["python.exe", "server.py"], cwd=str(hub_dir)))
    assert hub_app._is_live_hub(4242) is False
