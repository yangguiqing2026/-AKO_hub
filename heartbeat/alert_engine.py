"""
alert_engine.py — 告警检查引擎。

后台线程每 30 秒轮询 heartbeats 表，检测：
1. 离线告警 — 超过 90 秒无心跳
2. 高 CPU 告警 — 连续 3 次 > 80%
3. 高错误率告警 — 最近 10 个任务失败 > 5 个

触发告警时写入 alerts 表，避免重复告警。

文档编号: AGE-TECH-AKO-HUB-020 §AlertEngine
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ── 常量 ───────────────────────────────────────────────────────────
DEFAULT_CHECK_INTERVAL: int = 30              # 检查间隔（秒）
OFFLINE_THRESHOLD_SECONDS: int = 90           # 离线判定阈值
CPU_HIGH_THRESHOLD: float = 80.0              # 高 CPU 阈值（%）
CPU_CONSECUTIVE_HIGH: int = 3                 # 连续高 CPU 次数阈值
ERROR_RATE_WINDOW: int = 10                   # 错误率检查窗口（最近 N 个任务）
ERROR_RATE_THRESHOLD: int = 5                 # 高错误率阈值（失败数 > N）
ALERT_COOLDOWN_SECONDS: int = 300             # 同类型告警冷却期（秒），避免重复触发
DB_TIMEOUT: float = 5.0


class AlertEngine:
    """
    告警检查引擎，后台线程定期扫描 heartbeats 表并生成告警。

    用法:
        engine = AlertEngine(db_path="ako_hub.db")
        engine.start()
        # ... 应用运行 ...
        engine.stop()
    """

    def __init__(
        self,
        db_path: str = "ako_hub.db",
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        on_alert: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Args:
            db_path: SQLite 数据库路径
            check_interval: 告警检查间隔（秒）
            on_alert: 告警触发时的回调函数，接收告警字典
        """
        self.db_path: str = db_path
        self.check_interval: int = check_interval
        self.on_alert: Optional[Callable[[Dict[str, Any]], None]] = on_alert

        self._thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._agent_cpu_history: Dict[str, List[float]] = {}   # agent_id → [cpu%, ...]

    # ── 公开方法 ───────────────────────────────────────────────────

    def start(self) -> None:
        """启动告警检查后台线程。"""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._check_loop,
            name="alert-engine",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止告警检查线程。"""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=self.check_interval + 5)
        self._thread = None

    # ── 内部：检查循环 ─────────────────────────────────────────────

    def _check_loop(self) -> None:
        """告警检查主循环。"""
        while not self._stop_event.wait(timeout=self.check_interval):
            try:
                alerts = self._run_all_checks()
                for alert in alerts:
                    self._fire_alert(alert)
            except Exception:
                # 检查异常不影响下一轮
                pass

    def _run_all_checks(self) -> List[Dict[str, Any]]:
        """执行全部告警检查，返回新产生的告警列表。"""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        alerts: List[Dict[str, Any]] = []
        try:
            alerts.extend(self._check_offline(conn))
            alerts.extend(self._check_high_cpu(conn))
            alerts.extend(self._check_high_error_rate(conn))
        finally:
            conn.close()

        return alerts

    # ── 检查项 1：离线检测 ─────────────────────────────────────────

    def _check_offline(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        """
        查找最近 90 秒内无心跳但已注册的 Agent。

        逻辑：agents_registry 中所有 agent，检查其最新心跳时间，
        若超过 OFFLINE_THRESHOLD_SECONDS 且尚未恢复，生成告警。
        """
        cur = conn.execute("""
            SELECT
                a.agent_id, a.display_name, a.alert_level,
                h.timestamp AS last_heartbeat,
                CAST((strftime('%s','now') - strftime('%s', h.timestamp)) AS INTEGER) AS seconds_ago
            FROM agents_registry a
            LEFT JOIN (
                SELECT agent_id, MAX(id) AS latest_id
                FROM heartbeats
                GROUP BY agent_id
            ) latest ON a.agent_id = latest.agent_id
            LEFT JOIN heartbeats h ON h.id = latest.latest_id
        """)

        alerts = []
        for row in cur.fetchall():
            seconds_ago = row["seconds_ago"]
            # 无心跳记录 或 超过阈值
            if seconds_ago is None or seconds_ago > OFFLINE_THRESHOLD_SECONDS:
                agent_id = row["agent_id"]
                if not self._is_alert_active(conn, agent_id, "offline"):
                    alerts.append({
                        "agent_id": agent_id,
                        "alert_type": "offline",
                        "severity": row["alert_level"] or "warning",
                        "message": f"[{row['display_name']}] 离线"
                                   f"{f' ({seconds_ago}s 无心跳)' if seconds_ago else ' (暂无心跳记录)'}",
                    })

        return alerts

    # ── 检查项 2：高 CPU ───────────────────────────────────────────

    def _check_high_cpu(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        """
        检查每个 Agent 最近 CPU_CONSECUTIVE_HIGH 次心跳是否持续高负载。
        维护内存中的 CPU 历史列表，跨检查周期持久化。
        """
        # 获取每个 agent 的最近 N 次心跳 CPU
        cur = conn.execute("""
            SELECT h.agent_id, h.cpu_percent
            FROM heartbeats h
            INNER JOIN (
                SELECT agent_id, MAX(id) AS max_id
                FROM heartbeats
                GROUP BY agent_id
            ) latest ON h.agent_id = latest.agent_id
            WHERE h.id IN (
                SELECT id FROM heartbeats h2
                WHERE h2.agent_id = latest.agent_id
                ORDER BY h2.id DESC
                LIMIT ?
            )
        """, (CPU_CONSECUTIVE_HIGH,))

        # 按 agent 聚合
        agent_cpus: Dict[str, List[float]] = {}
        for row in cur.fetchall():
            aid = row["agent_id"]
            cpu = row["cpu_percent"]
            if cpu is not None:
                agent_cpus.setdefault(aid, []).append(cpu)

        alerts = []
        for agent_id, cpu_list in agent_cpus.items():
            if len(cpu_list) < CPU_CONSECUTIVE_HIGH:
                continue
            if all(c > CPU_HIGH_THRESHOLD for c in cpu_list):
                if not self._is_alert_active(conn, agent_id, "high_cpu"):
                    avg_cpu = round(sum(cpu_list) / len(cpu_list), 1)
                    alerts.append({
                        "agent_id": agent_id,
                        "alert_type": "high_cpu",
                        "severity": "warning",
                        "message": f"连续 {len(cpu_list)} 次高 CPU ({avg_cpu}%)",
                    })

        return alerts

    # ── 检查项 3：高错误率 ─────────────────────────────────────────

    def _check_high_error_rate(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        """
        统计最近 ERROR_RATE_WINDOW 个任务中失败数是否超过阈值。
        """
        cur = conn.execute("""
            SELECT h.agent_id, h.task_success, h.task_failed
            FROM heartbeats h
            INNER JOIN (
                SELECT agent_id, MAX(id) AS max_id
                FROM heartbeats
                GROUP BY agent_id
            ) latest ON h.agent_id = latest.agent_id
            WHERE h.id = latest.max_id
        """)

        alerts = []
        for row in cur.fetchall():
            agent_id = row["agent_id"]
            total = (row["task_success"] or 0) + (row["task_failed"] or 0)
            failed = row["task_failed"] or 0

            if total > 0 and failed > ERROR_RATE_THRESHOLD:
                if not self._is_alert_active(conn, agent_id, "high_error_rate"):
                    rate = round(failed / total * 100, 1)
                    alerts.append({
                        "agent_id": agent_id,
                        "alert_type": "high_error_rate",
                        "severity": "critical" if rate > 70 else "warning",
                        "message": f"最近 {total} 任务中失败 {failed} 个 ({rate}%)",
                    })

        return alerts

    # ── 告警去重与写入 ─────────────────────────────────────────────

    def _is_alert_active(self, conn: sqlite3.Connection, agent_id: str, alert_type: str) -> bool:
        """
        检查是否存在未恢复的同类型告警。

        逻辑：同 agent + 同类型 + 未恢复（resolved_at IS NULL）
        且在冷却期内（created_at 在 ALERT_COOLDOWN_SECONDS 内）不再重复生成。
        """
        cur = conn.execute("""
            SELECT created_at FROM alerts
            WHERE agent_id = ? AND alert_type = ? AND resolved_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
        """, (agent_id, alert_type))

        row = cur.fetchone()
        if row is None:
            return False

        created_at = row["created_at"]
        if created_at:
            try:
                created_ts = datetime.fromisoformat(created_at).timestamp()
                if time.time() - created_ts < ALERT_COOLDOWN_SECONDS:
                    return True
            except (ValueError, TypeError):
                pass

        return True   # 有未恢复告警，不重复触发

    def _fire_alert(self, alert: Dict[str, Any]) -> None:
        """写入告警到数据库并触发回调。"""
        # ── 写入 alerts 表 ──
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        try:
            conn.execute("""
                INSERT INTO alerts (agent_id, alert_type, severity, message, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                alert["agent_id"],
                alert["alert_type"],
                alert["severity"],
                alert["message"],
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

        # ── 回调通知 ──
        if self.on_alert:
            try:
                self.on_alert(alert)
            except Exception:
                pass


# ── 自检 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("AlertEngine 自检（需要有效的 ako_hub.db）...")
    engine = AlertEngine(db_path="ako_hub.db", check_interval=10)

    def _print_alert(a):
        print(f"  ⚠ [{a['severity']}] {a['agent_id']}: {a['message']}")

    engine.on_alert = _print_alert
    engine.start()
    print("  告警引擎已启动，按 Ctrl+C 退出...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        print("  自检完成 ✓")
