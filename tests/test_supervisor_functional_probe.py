# ============================================
# Author: AKO_studio
# Tests for: supervisor 功能级探针（WO-HAI-20261005-005 方案A）
# 覆盖：产出新鲜度计算（纯函数）/ 功能判定（含冷启动宽限）
# ============================================

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_supervisor as sup  # noqa: E402


class TestOutputAge(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _touch(self, sub: str, name: str, age_hours: float) -> Path:
        d = self.tmp / sub
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text("{}", encoding="utf-8")
        ts = time.time() - age_hours * 3600
        os.utime(f, (ts, ts))
        return f

    def test_none_when_no_outputs(self):
        self.assertIsNone(sup._newest_output_age_hours(self.tmp))

    def test_fresh_patrol_report(self):
        self._touch("output/patrol", "guardian_patrol_100936_057b.json", 1.5)
        age = sup._newest_output_age_hours(self.tmp)
        self.assertIsNotNone(age)
        self.assertLess(age, 3)

    def test_newest_of_multiple_sources_wins(self):
        self._touch("output/patrol", "guardian_patrol_old.json", 40)
        self._touch("output/audit", "guardian_audit_202610.jsonl", 2)
        self._touch("output", "guardian_run_20260928.json", 100)
        age = sup._newest_output_age_hours(self.tmp)
        self.assertLess(age, 4)


class TestFunctionalVerdict(unittest.TestCase):

    def test_fresh_outputs_pass(self):
        self.assertTrue(sup._functional_ok(True, 2.0, 9999))

    def test_stale_outputs_fail_even_with_heartbeat(self):
        # 决定性场景：心跳新鲜（可能被 supervisor 代发）但产出停滞 → 判死
        self.assertFalse(sup._functional_ok(True, 30.0, 9999))

    def test_cold_start_grace_within_window(self):
        # 无产出 + 进程新起（<120min）→ 放行（未就绪）
        self.assertTrue(sup._functional_ok(True, None, 30))

    def test_cold_start_grace_expired(self):
        # 无产出 + 进程已运行超过宽限 → 判死
        self.assertFalse(sup._functional_ok(True, None, 200))

    def test_heartbeat_stale_fails(self):
        self.assertFalse(sup._functional_ok(False, 1.0, 9999))

    def test_boundary_26h(self):
        self.assertTrue(sup._functional_ok(True, 25.9, 9999))
        self.assertFalse(sup._functional_ok(True, 26.1, 9999))


class TestAdoptionSemantics(unittest.TestCase):

    def test_adopted_proc_semantics(self):
        """接管态：无 Popen 句柄时存活判定走匹配器（此处以不存在命令验证为 False）。"""
        ap = sup.AgentProc("AKO_test_nothing", ["python", "definitely_not_running_xyz.py"],
                           tempfile.gettempdir(), lambda a: True)
        self.assertFalse(ap.is_process_alive())
        ap.adopted = True
        self.assertFalse(ap.is_process_alive())  # 匹配器找不到既有实例 → 仍 False（保守）


if __name__ == "__main__":
    unittest.main()
