# ============================================
# Author: AKO_studio
# Tests for: supervisor 可观测性修复包（WO-HAI-20261005-008）
# 覆盖：P1-5 熔断拒绝可见化 / P1-7 PYTHONUNBUFFERED 注入 / P1-6 告警结果含 subject
# ============================================

import contextlib
import io
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_supervisor as sup  # noqa: E402


class TestThrottleVisibility(unittest.TestCase):
    """P1-5：熔断拒绝必须留痕（被拒对象 + 剩余冷却时间），此前为静默 return。"""

    def _ap(self, restarts):
        ap = sup.AgentProc("AKO_test_throttle", ["python", "noop.py"], Path("."), lambda a: True)
        ap.restarts = restarts
        ap.start = mock.Mock()
        return ap

    def test_throttled_logs_target_and_cooldown(self):
        now = 1_000_000.0
        ap = self._ap([now - 100, now - 200, now - 300])  # 3 笔全在 1 小时内 → 拒绝
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = ap.restart(now)
        self.assertFalse(result)
        ap.start.assert_not_called()  # 被拒时不得拉起
        out = buf.getvalue()
        self.assertIn("restart throttled", out)
        self.assertIn("AKO_test_throttle", out)   # 被拒对象
        self.assertIn("剩余冷却 3300s", out)       # 最早条目 now-300 → 3600-300=3300
        self.assertIn("3/3", out)

    def test_throttled_no_silent_return(self):
        """回归：修复前此路径静默无输出（WO-006 §四·观察1）。"""
        now = 2_000_000.0
        ap = self._ap([now - 10, now - 20, now - 30])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ap.restart(now)
        self.assertNotEqual(buf.getvalue().strip(), "")

    def test_allowed_restart_starts_and_records(self):
        now = 3_000_000.0
        ap = self._ap([now - 3700])  # 已滚出 1 小时窗口 → 放行
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = ap.restart(now)
        self.assertTrue(result)
        ap.start.assert_called_once()
        self.assertEqual(ap.restarts, [now])
        self.assertNotIn("throttled", buf.getvalue())

    def test_boundary_exactly_three_recent_throttles(self):
        now = 4_000_000.0
        ap = self._ap([now - 1, now - 2, now - 3, now - 4000])  # 第 4 笔过期
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = ap.restart(now)
        self.assertFalse(result)
        self.assertIn("3/3", buf.getvalue())


class TestUnbufferedSpawn(unittest.TestCase):
    """P1-7：spawn 时注入 PYTHONUNBUFFERED=1（等效 python -u，穿透启动链）。"""

    def test_spawn_env_sets_pythonunbuffered(self):
        ap = sup.AgentProc("AKO_test_spawn", [sys.executable, "-c", "import time; time.sleep(3)"],
                           Path("."), lambda a: True)
        captured = {}
        real_popen = subprocess.Popen

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return real_popen(*args, **kwargs)

        with mock.patch.object(sup.subprocess, "Popen", side_effect=fake_popen):
            ap.start()
        self.addCleanup(lambda: (ap.proc.kill(), ap.proc.wait()))
        self.assertEqual(captured.get("env", {}).get("PYTHONUNBUFFERED"), "1")

    def test_spawn_env_keeps_os_environ(self):
        """env 为 os.environ 的副本，不得清空既有环境（凭据等经环境注入）。"""
        ap = sup.AgentProc("AKO_test_spawn2", [sys.executable, "-c", "import time; time.sleep(3)"],
                           Path("."), lambda a: True)
        captured = {}
        real_popen = subprocess.Popen

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return real_popen(*args, **kwargs)

        import os
        with mock.patch.dict(os.environ, {"AKO_TEST_MARKER_X": "42"}):
            with mock.patch.object(sup.subprocess, "Popen", side_effect=fake_popen):
                ap.start()
        self.addCleanup(lambda: (ap.proc.kill(), ap.proc.wait()))
        self.assertEqual(captured.get("env", {}).get("AKO_TEST_MARKER_X"), "42")


class TestAlertResultFormat(unittest.TestCase):
    """P1-6（可见性侧）：告警结果单行含 subject，供【测试】前缀实证。"""

    def test_format_includes_subject(self):
        line = sup._format_alert_result(
            {"mode": "live", "sent": True, "subject": "【测试】[AKO-NetWatch] X", "error": ""})
        self.assertIn("mode=live", line)
        self.assertIn("sent=True", line)
        self.assertIn("【测试】", line)  # subject 原样可见
        self.assertIn("subject=【测试】[AKO-NetWatch] X", line)

    def test_format_tolerates_missing_fields(self):
        line = sup._format_alert_result({})
        self.assertIn("mode=None", line)
        self.assertIn("subject=", line)


if __name__ == "__main__":
    unittest.main()
