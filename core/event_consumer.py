# -*- coding: utf-8 -*-
"""事件总线消费者（2026-09-16）。

背景：`events/pending/` 自 2026-08-27 起积压 652 条，而 `completed/`、`failed/`
都是 0 —— 总线自建立起没有任何消费者。538 条是 AKO_monitor_agent 的 fuse_alert
（熔断告警，载荷写着 required_action="人工解除熔断"），连告警都无人过目。

职责：
  1. 把 pending 事件按类型分发处理，处理后 **ack**（移出 pending）；
  2. fuse_alert → 落 `alerts` 表：同一问题（同 agent + 同类型 + 同原因）折叠为
     一行未确认记录，避免每 30 分钟刷一条；
  3. 其余类型（register / law_* 等）归档放行 —— 宁可归档也不要继续积压；
  4. 坏事件进 failed 目录（可见、可查），不阻塞后续。

接线：由 core.pending_worker 的消费循环每轮调用一次（hub 常驻即消费者常驻）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.hub_db import HubDB
from events.bus import EventBus, get_event_bus

logger = logging.getLogger("ako_hub.event_consumer")

# 落 alerts 表的事件类型 → 表内 alert_type 兜底值
_ALERT_TYPES = {"fuse_alert": "fuse"}


def _fuse_summary(payload: Dict[str, Any]) -> Dict[str, str]:
    """从 fuse_alert 载荷提取落库字段（兼容 payload.alert 与平铺两种形态）。"""
    alert = payload.get("alert") if isinstance(payload.get("alert"), dict) else payload
    reason = str(alert.get("trigger_reason") or alert.get("reason") or "").strip()
    action = str(alert.get("required_action") or "").strip()
    message = reason
    if action:
        message = f"{reason}；{action}" if reason else action
    return {
        "agent_id": str(alert.get("trigger_source") or alert.get("agent_id") or "unknown"),
        "alert_type": str(alert.get("fuse_type") or _ALERT_TYPES["fuse_alert"]),
        "severity": str(alert.get("severity") or alert.get("current_state") or "warning"),
        "message": message or "（无描述）",
    }


def _ensure_alerts_table(db_path: str) -> None:
    """确保 alerts 表存在（幂等）。

    现网这张表是手工建的、没有任何模块负责创建 —— 消费者若不自建，落库会
    静默失败并把告警事件推进 failed（2026-09-16 实测）。DDL 与现网一致。
    """
    with HubDB(db_path) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                   id            INTEGER PRIMARY KEY AUTOINCREMENT,
                   agent_id      TEXT    NOT NULL,
                   alert_type    TEXT    NOT NULL,
                   severity      TEXT    NOT NULL DEFAULT 'info',
                   message       TEXT    NOT NULL DEFAULT '',
                   acknowledged  INTEGER NOT NULL DEFAULT 0,
                   created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                   resolved_at   TEXT
               )"""
        )


def _record_alert(db_path: str, fields: Dict[str, str]) -> bool:
    """落一行告警；已存在同 agent+类型+描述的未确认行则折叠（返回 False）。"""
    with HubDB(db_path) as db:
        existing = db.fetchone(
            "SELECT id FROM alerts WHERE agent_id=? AND alert_type=? AND message=? "
            "AND (acknowledged IS NULL OR acknowledged=0)",
            (fields["agent_id"], fields["alert_type"], fields["message"]),
        )
        if existing:
            return False
        db.execute(
            "INSERT INTO alerts (agent_id, alert_type, severity, message, acknowledged, created_at) "
            "VALUES (?,?,?,?,?, datetime('now'))",
            (fields["agent_id"], fields["alert_type"], fields["severity"], fields["message"], 0),
        )
    return True


def _alerts_db_path() -> str:
    """告警库 = 心跳库 ako_hub.db（与 dashboard.HEARTBEAT_DB、/api/health/alerts 同源）。

    2026-09-16 实测踩坑：起初按任务队列库（hub_meta.db）解析，告警落进了错库 ——
    看板读 ako_hub.db 永远看不到。落库目标必须是告警表的正主。
    """
    return str(Path(__file__).resolve().parent.parent / "ako_hub.db")


def drain_events_once(
    bus: Optional[EventBus] = None,
    db_path: Optional[str] = None,
    max_events: int = 200,
) -> Dict[str, int]:
    """消费一轮 pending 事件。返回统计：handled / collapsed / failed / pending_left。

    db_path 为告警库（缺省 ako_hub.db）；每轮上限 max_events：积压 652 条时
    几轮内自然排空，且不会长时间占用工作线程。
    """
    bus = bus or get_event_bus()
    if db_path is None:
        db_path = _alerts_db_path()

    stats = {"handled": 0, "collapsed": 0, "failed": 0, "pending_left": 0}
    _ensure_alerts_table(db_path)
    for event_file in sorted(bus.pending_dir.glob("*.json"))[:max_events]:
        try:
            event = json.loads(event_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning(f"事件不可解析，转 failed: {event_file.name} ({exc})")
            try:
                event_file.replace(bus.failed_dir / event_file.name)
            except OSError:
                pass
            stats["failed"] += 1
            continue

        event_id = str(event.get("event_id") or "")
        event_type = str(event.get("event_type") or "")
        try:
            if event_type in _ALERT_TYPES:
                fields = _fuse_summary(event.get("payload") or {})
                if _record_alert(db_path, fields):
                    logger.info(f"告警入库: {fields['agent_id']} / {fields['alert_type']}: {fields['message'][:80]}")
                else:
                    stats["collapsed"] += 1
            # 其余类型：归档放行（消费即归档，避免 pending 无限积压）
            if event_id:
                bus.ack(event_id, success=True)
            else:
                event_file.replace(bus.completed_dir / event_file.name)
            stats["handled"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"事件处理失败，转 failed: {event_file.name}: {type(exc).__name__}: {exc}")
            try:
                event_file.replace(bus.failed_dir / event_file.name)
            except OSError:
                pass
            stats["failed"] += 1

    stats["pending_left"] = len(list(bus.pending_dir.glob("*.json")))
    return stats
