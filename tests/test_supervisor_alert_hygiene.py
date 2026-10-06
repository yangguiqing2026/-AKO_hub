# ============================================
# Author: AKO_studio
# Tests for: supervisor 告警卫生三项（WO-HAI-20261006-009）
# 覆盖：静音规则（同 Agent+同异常类型 / 180 分钟 / 期满重报 / 跨实例持久化）
#       / 告警发送 append-only 落盘（时间/收件人/主题/成功失败）
#       / supervisor 自身 stdout 行缓冲（等效 PYTHONUNBUFFERED）
# 铁律：静音实测全程 mock——零真实外发（禁止真实邮件风暴）
# ============================================

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_supervisor as sup  # noqa: E402

KEY = "AKO_cluster_guardian_agent:DOWN"


class _Clock:
    """可推进的假时钟（静音窗口测试）。"""

    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeDispatcher:
    """假派发器：只计数，绝不触真实通道（禁止真实邮件风暴）。"""

    class _Notifier:
        email = "owner@example.com"

    def __init__(self):
        self.calls = []
        self.notifier = self._Notifier()

    def dispatch(self, health, decision, patrol_id, dry_run=False):
        self.calls.append(patrol_id)
        return {
            "sent": True,
            "mode": "live",
            "subject": "AKO-Guardian 值守告警 - AKO_cluster_guardian_agent DOWN",
            "error": "",
        }


class TestAlertSilence(unittest.TestCase):
    """静音规则：同 Agent+同异常类型，静默 180 分钟，期满重报（与 guardian 巡检告警同口径）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.clock = _Clock()

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger(self, path: Path | None = None):
        return sup.AlertSilenceLedger(path or (self.tmp / "silence.json"), clock=self.clock)

    def test_first_trigger_allowed_and_persisted(self):
        led = self._ledger()
        allowed, remaining = led.allow(KEY)
        self.assertTrue(allowed)
        self.assertEqual(remaining, 0.0)
        self.assertTrue((self.tmp / "silence.json").exists())  # 落盘

    def test_three_consecutive_within_window_only_first_allowed(self):
        """验收：模拟同 Agent 同类型连续 3 次触发，仅首封外发，静默期内 0 外发（mock）。"""
        led = self._ledger()
        results = [led.allow(KEY)[0] for _ in range(3)]
        self.assertEqual(results, [True, False, False])

    def test_suppressed_returns_remaining_seconds(self):
        led = self._ledger()
        led.allow(KEY)
        self.clock.advance(60)
        allowed, remaining = led.allow(KEY)
        self.assertFalse(allowed)
        self.assertAlmostEqual(remaining, sup.ALERT_SILENCE_MINUTES * 60 - 60, delta=1)

    def test_re_report_after_window_expiry(self):
        led = self._ledger()
        self.assertTrue(led.allow(KEY)[0])
        self.clock.advance(sup.ALERT_SILENCE_MINUTES * 60 - 1)
        self.assertFalse(led.allow(KEY)[0])  # 窗口内仍静默
        self.clock.advance(2)  # 期满
        allowed, _ = led.allow(KEY)
        self.assertTrue(allowed)  # 期满重报

    def test_distinct_conditions_are_independent(self):
        led = self._ledger()
        self.assertTrue(led.allow("AKO_a_agent:DOWN")[0])
        self.assertTrue(led.allow("AKO_b_agent:DOWN")[0])  # 不同 Agent 不受牵连
        self.assertTrue(led.allow("AKO_a_agent:DEGRADED")[0])  # 不同异常类型不受牵连
        self.assertFalse(led.allow("AKO_a_agent:DOWN")[0])

    def test_silence_survives_new_instance(self):
        """静音状态跨实例持久化（等效 supervisor 重启后仍静默）。"""
        self._ledger().allow(KEY)
        fresh = self._ledger()  # 新实例（模拟重启），读同一状态文件
        self.assertFalse(fresh.allow(KEY)[0])

    def test_corrupt_state_file_degrades_gracefully(self):
        p = self.tmp / "silence.json"
        p.write_text("{ 不是合法 JSON", encoding="utf-8")
        led = self._ledger(p)  # 不得抛异常
        self.assertTrue(led.allow(KEY)[0])  # 降级为可发


class TestFunctionalDownMock(unittest.TestCase):
    """功能死告警路径 mock 实测：全程假派发器，零真实外发。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.clock = _Clock()
        self.fake = _FakeDispatcher()
        self.ledger = sup.AlertSilenceLedger(self.tmp / "silence.json", clock=self.clock)
        self.log = self.tmp / "alerts.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _call(self):
        # 默认构建器被替换为 AssertionError——实现若绕过注入即测试爆响，绝不触真通道
        with mock.patch.object(sup, "_build_functional_down_dispatcher",
                               side_effect=AssertionError("测试中禁止构建真实派发器")):
            sup._notify_guardian_functional_down(
                "probe fail x3; output_age_hours=30.0",
                ledger=self.ledger,
                dispatcher_factory=lambda: self.fake,
                alert_log=self.log,
            )

    def _lines(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_three_consecutive_triggers_only_first_dispatches(self):
        """验收：连续 3 次触发仅首封外发（dispatch 1 次），静默期内 0 外发。"""
        for _ in range(3):
            self._call()
        self.assertEqual(len(self.fake.calls), 1)
        lines = self._lines()
        self.assertEqual(len(lines), 3)  # 3 条留痕：1 实发 + 2 静默
        self.assertEqual([l["sent"] for l in lines], [True, False, False])
        self.assertEqual(lines[1]["mode"], "suppressed_local")

    def test_dispatch_retried_after_window(self):
        self._call()
        self.clock.advance(sup.ALERT_SILENCE_MINUTES * 60 + 1)
        self._call()
        self.assertEqual(len(self.fake.calls), 2)  # 期满重报

    def test_failed_attempt_still_silences_within_window(self):
        """口径与 guardian AlertState 一致：允许即记时（尝试即算），失败也不风暴重试。"""
        boom = mock.Mock(side_effect=RuntimeError("SMTP 通道爆炸"))
        with mock.patch.object(sup, "_build_functional_down_dispatcher", boom):
            sup._notify_guardian_functional_down(
                "ev", ledger=self.ledger, dispatcher_factory=None, alert_log=self.log)  # 走默认→爆
        self._call()  # 窗口内再次触发
        self.assertEqual(len(self.fake.calls), 0)  # 被静默，未派发
        lines = self._lines()
        self.assertFalse(lines[0]["sent"])
        self.assertEqual(lines[1]["mode"], "suppressed_local")


class TestAlertSendLog(unittest.TestCase):
    """告警发送结果 append-only 落盘（时间/收件人/主题/成功失败）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.clock = _Clock()
        self.fake = _FakeDispatcher()
        self.ledger = sup.AlertSilenceLedger(self.tmp / "silence.json", clock=self.clock)
        self.log = self.tmp / "alerts.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _call(self, **kw):
        sup._notify_guardian_functional_down(
            "probe fail x3", ledger=self.ledger, dispatcher_factory=lambda: self.fake,
            alert_log=self.log, **kw)

    def _lines(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_log_fields_complete(self):
        self._call()
        rec = self._lines()[0]
        for field in ("ts", "caller", "agent_id", "verdict", "mode", "sent",
                      "recipient", "subject", "error", "evidence"):
            self.assertIn(field, rec)
        self.assertEqual(rec["sent"], True)
        self.assertEqual(rec["mode"], "live")
        self.assertEqual(rec["recipient"], "owner@example.com")
        self.assertIn("AKO_cluster_guardian_agent", rec["subject"])
        self.assertEqual(rec["caller"], "supervisor_watchdog")

    def test_log_appends_across_calls(self):
        self._call()
        self.clock.advance(sup.ALERT_SILENCE_MINUTES * 60 + 1)
        self._call()
        lines = self._lines()
        self.assertEqual(len(lines), 2)  # append 不覆盖
        self.assertTrue(all(l["sent"] for l in lines))

    def test_log_write_failure_does_not_raise(self):
        blocker = self.tmp / "blocker.txt"
        blocker.write_text("我是文件，不是目录", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._call(alert_log=blocker / "inner.jsonl")  # 父路径是文件 → 写入必失败
        self.assertIn("留痕", buf.getvalue())  # 有告警行，但不阻断
        self.assertEqual(len(self.fake.calls), 1)  # 派发照常

    def test_send_failure_logged_with_error(self):
        self.fake.dispatch = lambda *a, **k: {
            "sent": False, "mode": "live", "subject": "s", "error": "SMTP_PASS 未设置"}
        self._call()
        rec = self._lines()[0]
        self.assertFalse(rec["sent"])
        self.assertIn("SMTP_PASS", rec["error"])


class TestLineBufferedStdout(unittest.TestCase):
    """supervisor 自身 stdout 行缓冲（等效 PYTHONUNBUFFERED，铁律3）。"""

    def test_reconfigure_called_with_line_buffering(self):
        stream = mock.Mock()
        ok = sup._force_line_buffered_stdout(stream)
        self.assertTrue(ok)
        stream.reconfigure.assert_called_once_with(line_buffering=True)

    def test_tolerates_missing_reconfigure(self):
        class _Bare:
            pass

        self.assertFalse(sup._force_line_buffered_stdout(_Bare()))  # 不抛异常

    def test_tolerates_reconfigure_error(self):
        stream = mock.Mock()
        stream.reconfigure.side_effect = ValueError("不支持")
        self.assertFalse(sup._force_line_buffered_stdout(stream))  # 不抛异常


if __name__ == "__main__":
    unittest.main()
