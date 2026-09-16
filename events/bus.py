# ============================================
# Author: AKO_studio
# Module: bus.py — Agent 间事件总线 v1.0
# Description: 替代"人工读文件"的异步通知机制
# ============================================

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

# ── 路径常量 ───────────────────────────────────────────────────────
_PKG_DIR = Path(__file__).resolve().parent.parent  # AKO_hub/
AKO_ROOT = _PKG_DIR.parent  # D:/AKO
EVENTS_PENDING_DIR = AKO_ROOT / "events" / "pending"
EVENTS_COMPLETED_DIR = AKO_ROOT / "events" / "completed"
EVENTS_FAILED_DIR = AKO_ROOT / "events" / "failed"
LOGS_DIR = AKO_ROOT / "logs"

for d in [EVENTS_PENDING_DIR, EVENTS_COMPLETED_DIR, EVENTS_FAILED_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── 日志 ───────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("ako_infra.bus")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        dt = datetime.now().strftime("%Y%m%d")
        fh = logging.FileHandler(str(LOGS_DIR / f"infra_{dt}.log"), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
        fh.setFormatter(formatter)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger

logger = _setup_logging()

# ── 有效事件类型 ───────────────────────────────────────────────────
VALID_EVENT_TYPES = {
    "dispatch_requested": "dispatch.py 收到新指令",
    "agent_created": "新 Agent 脚手架创建完成",
    "qc_requested": "QC 审计被请求",
    "qc_complete": "QC 审计完成",
    "qc_pass": "QC 通过",
    "qc_fail": "QC 未通过",
    "stage_advanced": "Agent 进入新阶段",
    "human_review_required": "需要人工审核",
    "blocker_added": "Guardian 写入了 blocker",
    "blocker_removed": "Guardian 清除了 blocker",
    "alert_raised": "Guardian 发出告警",
    "dispatch_complete": "dispatch 指令处理完成",
    "agent_shipped": "Agent 已发布",
    "fuse_alert": "监控熔断告警（AKO_monitor_agent 发出，需人工解除或超时自解）",
}


class EventBus:
    """AKO 事件总线 — 基于文件的消息队列"""

    def __init__(self, root: Path = AKO_ROOT):
        self.pending_dir = Path(root) / "events" / "pending"
        self.completed_dir = Path(root) / "events" / "completed"
        self.failed_dir = Path(root) / "events" / "failed"
        for d in [self.pending_dir, self.completed_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _generate_event_id(self) -> str:
        """生成唯一事件 ID"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = str(uuid4())[:8]
        return f"EVT-{ts}-{uid}"

    def publish(
        self,
        source_agent: str,
        event_type: str,
        payload: Dict[str, Any],
        target_agent: str = "*",
        ttl_seconds: int = 3600,
    ) -> str:
        """发布事件，返回 event_id

        Args:
            source_agent: 事件源 Agent ID
            event_type: 事件类型（必须在 VALID_EVENT_TYPES 中）
            payload: 事件负载数据
            target_agent: 目标 Agent ID, "*" 表示广播
            ttl_seconds: 事件存活时间（秒），超时自动清理

        Returns:
            event_id: 事件唯一标识
        """
        if event_type not in VALID_EVENT_TYPES:
            logger.warning(f"未知事件类型: {event_type}，允许发布但请注意")

        event_id = self._generate_event_id()
        now = datetime.now(timezone(timedelta(hours=8)))

        event: Dict[str, Any] = {
            "event_id": event_id,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "event_type": event_type,
            "payload": payload,
            "timestamp": now.isoformat(),
            "ttl_seconds": ttl_seconds,
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
            "status": "pending",
        }

        # 文件名: {timestamp}_{source}_{type}_{event_id}.json
        ts = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename = f"{ts}_{source_agent}_{event_type}_{event_id}.json"
        filepath = self.pending_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(event, f, ensure_ascii=False, indent=2)

        logger.info(
            json.dumps({
                "action": "event_published",
                "event_id": event_id,
                "source": source_agent,
                "target": target_agent,
                "type": event_type,
            }, ensure_ascii=False)
        )
        return event_id

    def consume(
        self, target_agent: str, event_types: Optional[List[str]] = None, max_events: int = 50
    ) -> List[Dict[str, Any]]:
        """消费指定目标 Agent 的事件列表

        Args:
            target_agent: 目标 Agent ID（用于过滤 target_agent 字段）
            event_types: 过滤的事件类型列表，None = 全部
            max_events: 最多返回事件数

        Returns:
            event 列表（按时间升序）
        """
        events: List[Dict[str, Any]] = []
        now = datetime.now(timezone(timedelta(hours=8)))

        if not self.pending_dir.exists():
            return events

        for event_file in sorted(self.pending_dir.glob("*.json")):
            if len(events) >= max_events:
                break
            try:
                with open(event_file, "r", encoding="utf-8") as f:
                    event = json.load(f)

                # 检查目标
                et = event.get("target_agent", "*")
                if et != "*" and et != target_agent:
                    continue

                # 检查事件类型
                if event_types and event.get("event_type") not in event_types:
                    continue

                # 检查过期
                expires_str = event.get("expires_at", "")
                if expires_str:
                    try:
                        expires_dt = datetime.fromisoformat(expires_str)
                        if now > expires_dt:
                            # 过期事件，移入 failed
                            self.ack(event.get("event_id", ""), success=False)
                            continue
                    except (ValueError, TypeError):
                        pass

                events.append(event)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"读取事件文件失败: {event_file.name} - {e}")

        return events

    def ack(self, event_id: str, success: bool = True) -> bool:
        """确认事件处理完成

        Args:
            event_id: 事件 ID
            success: True = 移入 completed, False = 移入 failed

        Returns:
            是否成功确认
        """
        target_dir = self.completed_dir if success else self.failed_dir

        for event_file in self.pending_dir.glob(f"*_{event_id}.json"):
            try:
                with open(event_file, "r", encoding="utf-8") as f:
                    event = json.load(f)

                event["status"] = "completed" if success else "failed"
                event["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()

                dest = target_dir / event_file.name
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(event, f, ensure_ascii=False, indent=2)

                event_file.unlink()  # 删除 pending 中的原文件
                logger.info(f"Event {event_id} -> {'completed' if success else 'failed'}")
                return True
            except Exception as e:
                logger.error(f"确认事件失败: {event_id} - {e}")

        logger.warning(f"事件未找到: {event_id}")
        return False

    def get_pending_count(self, target_agent: str = "*", event_type: Optional[str] = None) -> int:
        """获取待处理事件数量"""
        count = 0
        if not self.pending_dir.exists():
            return 0
        for event_file in self.pending_dir.glob("*.json"):
            try:
                with open(event_file, "r", encoding="utf-8") as f:
                    event = json.load(f)
                et = event.get("target_agent", "*")
                if et != "*" and et != target_agent:
                    continue
                if event_type and event.get("event_type") != event_type:
                    continue
                count += 1
            except Exception:
                pass
        return count

    def cleanup_expired(self) -> int:
        """清理过期事件，返回清理数量"""
        cleaned = 0
        now = datetime.now(timezone(timedelta(hours=8)))

        if not self.pending_dir.exists():
            return 0

        for event_file in list(self.pending_dir.glob("*.json")):
            try:
                with open(event_file, "r", encoding="utf-8") as f:
                    event = json.load(f)

                expires_str = event.get("expires_at", "")
                if expires_str:
                    expires_dt = datetime.fromisoformat(expires_str)
                    if now > expires_dt:
                        shutil.move(str(event_file), str(self.failed_dir / event_file.name))
                        cleaned += 1
            except Exception:
                pass

        if cleaned > 0:
            logger.info(f"清理过期事件: {cleaned} 个")
        return cleaned

    def broadcast_qc_result(self, agent_id: str, score: int, result: str, report_path: str = "") -> str:
        """便捷方法: 广播 QC 结果"""
        return self.publish(
            source_agent="AKO_qc_agent",
            target_agent="AKO_pipeline_agent",
            event_type="qc_complete",
            payload={
                "agent_id": agent_id,
                "qc_report_path": report_path,
                "result": result,
                "score": score,
            },
            ttl_seconds=3600,
        )

    def broadcast_stage_change(self, agent_id: str, from_stage: str, to_stage: str) -> str:
        """便捷方法: 广播阶段变化"""
        return self.publish(
            source_agent="AKO_pipeline_agent",
            target_agent="*",
            event_type="stage_advanced",
            payload={
                "agent_id": agent_id,
                "from_stage": from_stage,
                "to_stage": to_stage,
            },
            ttl_seconds=1800,
        )

    def broadcast_alert(self, alert_data: Dict[str, Any]) -> str:
        """便捷方法: 广播告警"""
        return self.publish(
            source_agent=alert_data.get("source_agent", "AKO_cluster_guardian_agent"),
            target_agent="AKO_pipeline_agent",
            event_type="alert_raised",
            payload=alert_data,
            ttl_seconds=7200,
        )


# ── 全局单例 ───────────────────────────────────────────────────────
_event_bus_instance: Optional[EventBus] = None


def get_event_bus(root: Path = AKO_ROOT) -> EventBus:
    """获取全局 EventBus 单例"""
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus(root=root)
    return _event_bus_instance


# ── CLI ─────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="AKO 事件总线 CLI")
    sub = parser.add_subparsers(dest="cmd")

    # publish
    p_pub = sub.add_parser("publish", help="发布事件")
    p_pub.add_argument("--source", required=True, help="源 Agent ID")
    p_pub.add_argument("--target", default="*", help="目标 Agent ID")
    p_pub.add_argument("--type", dest="etype", required=True, help="事件类型")
    p_pub.add_argument("--payload", default="{}", help="JSON payload")
    p_pub.add_argument("--ttl", type=int, default=3600, help="存活时间(秒)")

    # consume
    p_con = sub.add_parser("consume", help="消费事件")
    p_con.add_argument("--agent", required=True, help="目标 Agent ID")
    p_con.add_argument("--types", default="", help="事件类型(逗号分隔)")
    p_con.add_argument("--max", type=int, default=10, help="最大数量")

    # ack
    p_ack = sub.add_parser("ack", help="确认事件")
    p_ack.add_argument("--event-id", required=True, help="事件 ID")
    p_ack.add_argument("--fail", action="store_true", help="标记为失败")

    # count
    p_cnt = sub.add_parser("count", help="统计待处理事件")
    p_cnt.add_argument("--agent", default="*", help="目标 Agent ID")

    # cleanup
    sub.add_parser("cleanup", help="清理过期事件")

    args = parser.parse_args()
    bus = get_event_bus()

    if args.cmd == "publish":
        payload = json.loads(args.payload)
        eid = bus.publish(args.source, args.etype, payload, args.target, args.ttl)
        print(json.dumps({"status": "OK", "event_id": eid}, ensure_ascii=False))
    elif args.cmd == "consume":
        types = [t.strip() for t in args.types.split(",") if t.strip()] if args.types else None
        events = bus.consume(args.agent, event_types=types, max_events=args.max)
        print(json.dumps(events, ensure_ascii=False, indent=2))
    elif args.cmd == "ack":
        ok = bus.ack(args.event_id, success=not args.fail)
        print(json.dumps({"status": "OK" if ok else "FAIL"}))
    elif args.cmd == "count":
        cnt = bus.get_pending_count(args.agent)
        print(json.dumps({"pending_count": cnt}))
    elif args.cmd == "cleanup":
        cnt = bus.cleanup_expired()
        print(json.dumps({"cleaned": cnt}))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()