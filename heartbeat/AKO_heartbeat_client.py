"""
AKO_heartbeat_client.py — Agent 端心跳客户端。

嵌入每个 Agent 进程，后台线程定期向 Hub 发送心跳 + 系统资源数据。
文档编号: AGE-TECH-AKO-HUB-020 §HeartbeatClient
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import psutil
import requests


# ── 常量 ───────────────────────────────────────────────────────────
DEFAULT_HEARTBEAT_INTERVAL: int = 30          # 心跳间隔（秒）
DEFAULT_HUB_URL: str = "http://localhost:5000/heartbeat"
REQUEST_TIMEOUT: int = 5                       # HTTP 请求超时（秒）
MAX_TASK_HISTORY: int = 20                     # 最近任务记录条数


class HeartbeatClient:
    """
    Agent 端心跳客户端，后台线程定期向 Hub 上报存活状态。

    职责：
    1. 采集系统资源（CPU / 内存 / 磁盘）
    2. 采集当前进程状态（任务数 / 错误数）
    3. 定期 POST 到 Hub 心跳端点
    4. 提供 report_task() 上报单次任务执行状态

    用法:
        client = HeartbeatClient(agent_id="AKO_quote_agent", hub_url="http://localhost:5000/heartbeat")
        client.start()
        # ... 业务代码 ...
        client.report_task(task_id="task-001", status="completed")
        client.stop()
    """

    def __init__(
        self,
        agent_id: str,
        hub_url: str = DEFAULT_HUB_URL,
        heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
        on_heartbeat_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """
        Args:
            agent_id: Agent 唯一标识符，对应 agents_registry.agent_id
            hub_url: Hub 心跳接收端点完整 URL
            heartbeat_interval: 心跳间隔（秒），建议 >= 10
            on_heartbeat_error: 心跳失败时的可选回调
        """
        self.agent_id: str = agent_id
        self.hub_url: str = hub_url
        self.heartbeat_interval: int = max(heartbeat_interval, 5)
        self.on_heartbeat_error: Optional[Callable[[Exception], None]] = on_heartbeat_error

        # ── 运行时状态 ──
        self._thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._session_id: str = uuid.uuid4().hex[:12]
        self._started_at: float = time.time()

        # ── 任务统计（线程安全由 GIL 保障，轻量级） ──
        self._task_total: int = 0
        self._task_success: int = 0
        self._task_failed: int = 0
        self._task_history: list[Dict[str, Any]] = []   # 最近任务记录
        self._last_task: Optional[str] = None
        self._last_task_status: Optional[str] = None

    # ── 公开方法 ───────────────────────────────────────────────────

    def start(self) -> None:
        """启动后台心跳线程。幂等操作：若已运行则忽略。"""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"hb-{self.agent_id[:16]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止后台心跳线程。阻塞等待线程结束。"""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=self.heartbeat_interval + 5)
        self._thread = None

    def report_task(self, task_id: str, status: str, meta: Optional[Dict[str, Any]] = None) -> None:
        """
        上报单次任务执行状态。

        Args:
            task_id: 任务唯一 ID
            status: 状态，建议 completed / failed / running
            meta: 附加元数据（如错误信息、耗时等）
        """
        self._task_total += 1
        self._last_task = task_id
        self._last_task_status = status

        if status == "completed":
            self._task_success += 1
        elif status == "failed":
            self._task_failed += 1

        record = {
            "task_id": task_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "meta": meta or {},
        }
        self._task_history.append(record)

        # 保持最近 N 条
        if len(self._task_history) > MAX_TASK_HISTORY:
            self._task_history = self._task_history[-MAX_TASK_HISTORY:]

    # ── 内部方法 ───────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """后台心跳主循环。"""
        while not self._stop_event.wait(timeout=self.heartbeat_interval):
            try:
                payload = self._build_payload()
                self._send_heartbeat(payload)
            except Exception as e:
                if self.on_heartbeat_error:
                    try:
                        self.on_heartbeat_error(e)
                    except Exception:
                        pass  # 回调异常不影响主循环

    def _build_payload(self) -> Dict[str, Any]:
        """构造心跳请求体。"""
        # 系统资源
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        proc = psutil.Process(os.getpid())

        # 内存（MB）
        try:
            mem_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            mem_mb = mem.used / (1024 * 1024)

        # 响应时间（毫秒）—— 进程启动以来的 CPU 时间，近似衡量繁忙程度
        try:
            cpu_times = proc.cpu_times()
            response_time_ms = (cpu_times.user + cpu_times.system) * 1000
        except Exception:
            response_time_ms = 0.0

        return {
            "agent_id": self.agent_id,
            "session_id": self._session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "alive",
            "hostname": platform.node(),
            "uptime_seconds": int(time.time() - self._started_at),
            # 系统资源
            "cpu_percent": round(cpu, 2),
            "memory_mb": round(mem_mb, 1),
            "disk_percent": disk.percent,
            # 进程统计
            "task_total": self._task_total,
            "task_success": self._task_success,
            "task_failed": self._task_failed,
            "last_task": self._last_task,
            "last_task_status": self._last_task_status,
            "response_time_ms": round(response_time_ms, 2),
            # 最近任务摘要（仅发最近 5 条）
            "recent_tasks": self._task_history[-5:],
        }

    def _send_heartbeat(self, payload: Dict[str, Any]) -> None:
        """发送心跳 POST 请求。"""
        try:
            resp = requests.post(
                self.hub_url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except requests.RequestException:
            # 网络错误静默放过，下次心跳重试即可
            pass


# ── 自检 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("HeartbeatClient 自检...")
    client = HeartbeatClient(agent_id="test_agent_001")
    client.start()
    print(f"  心跳线程已启动 (interval={client.heartbeat_interval}s)")
    client.report_task("task-001", "completed")
    client.report_task("task-002", "failed", {"error": "连接超时"})
    time.sleep(3)
    print(f"  任务统计: total={client._task_total}, success={client._task_success}, failed={client._task_failed}")
    client.stop()
    print("  自检完成 ✓")
