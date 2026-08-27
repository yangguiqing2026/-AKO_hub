# ============================================
# Author: AKO_studio
# Module: schemas.py — 事件 Schema 定义 v2.0
# Description: Pydantic 事件契约，所有 Agent 通信格式统一
# ============================================

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Literal, Any
from uuid import uuid4

try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = object  # type: ignore[assignment]
    Field = lambda *a, **kw: None


def _tz_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


class EventType(str, Enum):
    """事件类型枚举 — 禁止自由字符串"""
    # 生命周期
    AGENT_CREATED = "agent_created"
    AGENT_DELETED = "agent_deleted"

    # 流水线
    QC_STARTED = "qc_started"
    QC_COMPLETE = "qc_complete"
    VISUAL_STARTED = "visual_started"
    VISUAL_COMPLETE = "visual_complete"
    STATE_TRANSITION = "state_transition"

    # 人工
    HOLD_TRIGGERED = "hold_triggered"
    HOLD_RESOLVED = "hold_resolved"

    # 异常
    BLOCK_TRIGGERED = "block_triggered"
    BLOCK_RESOLVED = "block_resolved"
    TIMEOUT = "timeout"

    # 系统
    ROLLBACK = "rollback"
    SYSTEM_HEARTBEAT = "system_heartbeat"


class BaseEvent(BaseModel):
    """所有事件基类"""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=_tz_now)
    source_agent: str = Field(..., description="触发事件的 Agent 标识")
    version: str = Field(default="2.0")


class QCEvent(BaseEvent):
    """QC 完成事件"""
    event_type: Literal[EventType.QC_COMPLETE] = EventType.QC_COMPLETE
    target_agent: str = Field(..., description="被质检的 Agent 名称")
    result: Literal["PASS", "FAIL", "SKIP", "EXEMPT"] = Field(...)
    score: Optional[int] = Field(None, ge=0, le=100)
    veto_items: list[str] = Field(default_factory=list)
    report_path: Optional[str] = Field(None, description="qc_report.json 路径")


class StateTransitionEvent(BaseEvent):
    """状态迁移事件"""
    event_type: Literal[EventType.STATE_TRANSITION] = EventType.STATE_TRANSITION
    agent_id: str = Field(..., description="状态变更的 Agent")
    from_state: str = Field(..., description="原状态")
    to_state: str = Field(..., description="目标状态")
    reason: Optional[str] = Field(None)


class BlockEvent(BaseEvent):
    """Guardian 阻断事件"""
    event_type: Literal[EventType.BLOCK_TRIGGERED] = EventType.BLOCK_TRIGGERED
    target_agent: Optional[str] = Field(None, description="被阻断的 Agent，None=全局阻断")
    severity: Literal["warning", "critical", "fatal"] = Field(...)
    message: str = Field(...)
    suggestion: Optional[str] = Field(None)


class HoldEvent(BaseEvent):
    """人工门禁事件"""
    event_type: Literal[EventType.HOLD_TRIGGERED] = EventType.HOLD_TRIGGERED
    agent_id: str = Field(...)
    condition: str = Field(..., description="触发门禁的条件")
    required_approval: str = Field(default="senior", description="所需审批级别")


class HeartbeatEvent(BaseEvent):
    """系统心跳事件"""
    event_type: Literal[EventType.SYSTEM_HEARTBEAT] = EventType.SYSTEM_HEARTBEAT
    active_agents: int = Field(...)
    pipeline_state: Optional[str] = Field(None)