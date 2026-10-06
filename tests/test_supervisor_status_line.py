# ============================================
# Author: AKO_studio
# Tests for: supervisor 存活判定/状态行（WO-HAI-20261005-007）
# 覆盖：句柄失效后既有实例复核（根因回归）/ "探针真但状态行假 OFFLINE"回归 /
#       句柄存活路径保持 / 原接管态语义保持
# ============================================

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_supervisor as sup  # noqa: E402


def _mk(probe=None):
    return sup.AgentProc(
        "AKO_test_agent",
        ["python", "main.py"],
        Path("."),
        probe if probe is not None else (lambda a: True),
    )


def _attach_dead_handle(ap):
    """模拟 restart().start() 后子进程退出的形态：proc 句柄存在但已死。"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=10)
    ap.proc = p
    return ap


class TestDeadHandleRecovery(unittest.TestCase):
    """WO-007 根因回归：'句柄死 + adopted=False'不得遮蔽既有活实例。

    修复前 is_process_alive() 在 proc 非空时直接返回 poll() is None，
    匹配器被永久跳过 → 状态行恒 OFFLINE（WO-006 §四·观察4 矛盾）。
    """

    def test_dead_handle_with_live_instance_is_alive(self):
        """回归①（修复前红→修复后绿）：句柄死，但匹配器见活实例 → 判存活。"""
        ap = _attach_dead_handle(_mk())
        ap.adopted = False
        with mock.patch.object(sup, "_agent_already_running", return_value=True):
            self.assertTrue(ap.is_process_alive())

    def test_dead_handle_without_instance_is_dead(self):
        """句柄死且无既有实例 → 仍判死（保持保守语义）。"""
        ap = _attach_dead_handle(_mk())
        ap.adopted = False
        with mock.patch.object(sup, "_agent_already_running", return_value=False):
            self.assertFalse(ap.is_process_alive())

    def test_probe_true_but_status_false_regression(self):
        """回归②（WO-007 P1-2 指定用例，修复前红→修复后绿）：
        探针真（活实例在 + 探针通过）→ 状态必须在线，不得假 OFFLINE。"""
        ap = _attach_dead_handle(_mk(probe=lambda a: True))
        ap.adopted = False
        with mock.patch.object(sup, "_agent_already_running", return_value=True):
            self.assertTrue(ap.is_online())

    def test_dead_handle_probe_fail_is_offline(self):
        """句柄死、活实例在，但探针判死（功能死）→ 离线（重启路径开启）。"""
        ap = _attach_dead_handle(_mk(probe=lambda a: False))
        ap.adopted = False
        with mock.patch.object(sup, "_agent_already_running", return_value=True):
            self.assertFalse(ap.is_online())


class TestSemanticsPreserved(unittest.TestCase):
    """修复不得破坏既有语义。"""

    def test_live_handle_true_without_matcher(self):
        """句柄存活 → 直接判活（不咨询匹配器）。"""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        ap = _mk()
        ap.proc = p
        with mock.patch.object(sup, "_agent_already_running", return_value=False):
            self.assertTrue(ap.is_process_alive())

    def test_none_proc_adopted_matcher_semantics_kept(self):
        """接管态（proc=None + adopted=True）：仍按匹配器复核。"""
        ap = _mk()
        ap.adopted = True
        with mock.patch.object(sup, "_agent_already_running", return_value=True):
            self.assertTrue(ap.is_process_alive())
        with mock.patch.object(sup, "_agent_already_running", return_value=False):
            self.assertFalse(ap.is_process_alive())

    def test_none_proc_unanopted_uses_matcher(self):
        """proc=None（含 adopted=False）：统一回退匹配器（修复后语义）。"""
        ap = _mk()
        ap.adopted = False
        with mock.patch.object(sup, "_agent_already_running", return_value=True):
            self.assertTrue(ap.is_process_alive())


if __name__ == "__main__":
    unittest.main()
