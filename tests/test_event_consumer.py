# -*- coding: utf-8 -*-
"""事件总线消费者（2026-09-16）。

现场：`events/pending/` 积压 652 条（最老 2026-08-27），而 `completed/`、`failed/`
都是 0 —— 总线自建立起**没有任何消费者**。其中 538 条是 AKO_monitor_agent 的
fuse_alert（熔断告警，载荷里写着 "required_action: 人工解除熔断"），连告警都无人过目。

本消费器：把 pending 按类型分发 → fuse_alert 落 alerts 表（同一问题折叠为一行）
→ 全部 ack（移出 pending）。未知类型归档而非卡住。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import event_consumer  # noqa: E402
from core.hub_db import HubDB  # noqa: E402
from events.bus import VALID_EVENT_TYPES, EventBus  # noqa: E402

FUSE = {
    "alert_id": "FUSE-20260916-163549-network",
    "timestamp": "2026-09-16T08:35:49+00:00",
    "fuse_type": "system",
    "trigger_source": "AKO_monitor_agent",
    "trigger_reason": "普通网络 67% > 20%，来自 192.168.1.1",
    "current_state": "suspended",
    "required_action": "人工解除熔断，或等待超时自动解除",
    "notify_targets": ["human_officer@akobuild.cloud"],
}


def _env(monkeypatch, tmp_path):
    """临时 root（事件目录）+ 临时 hub 库。"""
    bus = EventBus(root=tmp_path)
    db_path = str(tmp_path / "hub_meta.db")
    HubDB(db_path).init_schema()
    return bus, db_path


def _alerts(db_path):
    with HubDB(db_path) as db:
        return db.fetchall("SELECT agent_id, alert_type, message, acknowledged FROM alerts")


def test_fuse_alert_type_is_registered() -> None:
    """fuse_alert 是监控在用的真实类型，不该再报"未知事件类型"。"""
    assert "fuse_alert" in VALID_EVENT_TYPES


def test_fuse_alert_recorded_and_acked(monkeypatch, tmp_path) -> None:
    bus, db_path = _env(monkeypatch, tmp_path)
    bus.publish("AKO_monitor_agent", "fuse_alert", {"alert": FUSE}, target_agent="AKO_monitor_agent")

    result = event_consumer.drain_events_once(bus=bus, db_path=db_path)

    assert result["handled"] == 1
    assert result["pending_left"] == 0                   # 已移出 pending
    assert len(list(bus.completed_dir.glob("*.json"))) == 1
    rows = _alerts(db_path)
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "AKO_monitor_agent"
    assert "普通网络" in rows[0]["message"] and "人工解除" in rows[0]["message"]


def test_duplicate_fuse_alerts_collapse(monkeypatch, tmp_path) -> None:
    """同一问题反复熔断（每 30 分钟一条）折叠成一行，不刷屏。"""
    bus, db_path = _env(monkeypatch, tmp_path)
    for i in range(5):
        ev = dict(FUSE, alert_id=f"FUSE-x-{i}")
        bus.publish("AKO_monitor_agent", "fuse_alert", {"alert": ev}, target_agent="AKO_monitor_agent")

    result = event_consumer.drain_events_once(bus=bus, db_path=db_path)

    assert result["handled"] == 5
    assert result["collapsed"] == 4
    assert len(_alerts(db_path)) == 1


def test_other_event_types_are_archived_not_stuck(monkeypatch, tmp_path) -> None:
    """register/law_* 等也无消费者：归档并放行，不让 pending 继续积压。"""
    bus, db_path = _env(monkeypatch, tmp_path)
    bus.publish("AKO_law_agent", "law_promulgation", {"law": "X"}, target_agent="*")
    bus.publish("AKO_quote_agent", "register", {"agent": "AKO_quote_agent"}, target_agent="*")

    result = event_consumer.drain_events_once(bus=bus, db_path=db_path)

    assert result["handled"] == 2
    assert result["pending_left"] == 0
    assert _alerts(db_path) == []                        # 非告警类型不落 alerts 表


def test_malformed_event_goes_failed(monkeypatch, tmp_path) -> None:
    """坏事件进 failed 目录（可见），不阻塞后续消费。"""
    bus, db_path = _env(monkeypatch, tmp_path)
    bad = bus.pending_dir / "20260916_000000_000_broken_EVT-broken.json"
    bad.write_text("{not json", encoding="utf-8")
    bus.publish("AKO_monitor_agent", "fuse_alert", {"alert": FUSE}, target_agent="AKO_monitor_agent")

    result = event_consumer.drain_events_once(bus=bus, db_path=db_path)

    assert result["failed"] == 1
    assert result["handled"] == 1
    assert len(list(bus.failed_dir.glob("*.json"))) == 1


def test_alert_row_shape_matches_table(monkeypatch, tmp_path) -> None:
    """落库字段与 alerts 表契约一致（severity 缺省用 fuse_type）。"""
    bus, db_path = _env(monkeypatch, tmp_path)
    bus.publish("AKO_monitor_agent", "fuse_alert", {"alert": FUSE}, target_agent="AKO_monitor_agent")
    event_consumer.drain_events_once(bus=bus, db_path=db_path)
    with HubDB(db_path) as db:
        row = db.fetchone("SELECT * FROM alerts")
    assert row["alert_type"] == "system"
    assert row["severity"]
    assert row["acknowledged"] in (0, None)


def test_alerts_go_to_heartbeat_db_not_queue_db() -> None:
    """落库目标必须是告警表的正主（ako_hub.db 心跳库）。

    回归：首版按任务队列库（hub_meta.db）解析 → 落进错库，看板
    /api/health/alerts（读 ako_hub.db）永远看不到。
    """
    assert event_consumer._alerts_db_path().endswith("ako_hub.db")
