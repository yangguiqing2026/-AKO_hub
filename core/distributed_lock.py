"""
AKO Hub — 轻量级分布式锁
distributed_lock.py: 基于 SQLite 的 hub_lock 表，实现双机一写多读。

约束：
  - 非严格分布式锁（无 ZooKeeper / etcd），适用于双机通过百度云盘同步场景。
  - 依赖锁持有者定期释放或超时自动释放，防止 crash 后死锁。
  - 锁粒度：整库级，同一时刻仅一台机器执行 Master Graph 写入。

用法：
    from core.distributed_lock import DistributedLock
    lock = DistributedLock("D:/BaiduSyncdisk/AKO_Hub/age_hub.db", "machine_02")
    if lock.try_acquire(timeout=300):
        try:
            # 执行写入操作
            pass
        finally:
            lock.release()
    else:
        holder = lock.is_held()
        print(f"锁被 {holder} 持有，本机进入只读 standby")

文档编号: AGE-TECH-AKO-HUB-001 §P3
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ── 建表 SQL（幂等） ────────────────────────────────────────────

LOCK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hub_lock (
    lock_id INTEGER PRIMARY KEY CHECK(lock_id = 1),
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


class DistributedLock:
    """
    SQLite 级分布式锁。

    参数：
        db_path: age_hub.db 绝对路径
        machine_id: 当前机器标识，如 "machine_01"
    """

    def __init__(self, db_path: str, machine_id: str):
        self.db_path = str(Path(db_path).resolve())
        self.machine_id = machine_id
        self._ensure_table()

    # ── 内部 ───────────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        """确保 hub_lock 表存在。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(LOCK_TABLE_SQL)
            conn.commit()

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _expires(self, seconds: int) -> str:
        return (datetime.now() + timedelta(seconds=seconds)).isoformat()

    def _cleanup_expired(self) -> None:
        """清理已超时的锁。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM hub_lock WHERE expires_at < ?", (self._now(),))
            conn.commit()

    # ── 公开接口 ───────────────────────────────────────────────────

    def try_acquire(self, timeout_seconds: int = 300) -> bool:
        """
        尝试获取锁。

        Args:
            timeout_seconds: 锁超时时间，默认 300 秒（5 分钟）。
                             若机器 crash 未释放，超时后自动失效。

        Returns:
            True: 获取成功
            False: 锁被其他机器持有且未超时
        """
        self._cleanup_expired()
        now = self._now()
        expires = self._expires(timeout_seconds)

        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    "INSERT INTO hub_lock (lock_id, holder, acquired_at, expires_at) VALUES (1, ?, ?, ?)",
                    (self.machine_id, now, expires),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # 锁已被其他机器持有
                return False

    def release(self) -> bool:
        """
        释放锁。仅当持有者为当前 machine_id 时才成功。

        Returns:
            True: 释放成功
            False: 锁不属于本机或已不存在
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM hub_lock WHERE lock_id = 1 AND holder = ?",
                (self.machine_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def is_held(self) -> Optional[str]:
        """
        查询当前锁持有者。

        Returns:
            machine_id 字符串，或 None（无锁）
        """
        self._cleanup_expired()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT holder FROM hub_lock WHERE lock_id = 1"
            ).fetchone()
            return row[0] if row else None

    def is_held_by_self(self) -> bool:
        """当前锁是否由本机持有。"""
        holder = self.is_held()
        return holder == self.machine_id

    def force_release(self) -> bool:
        """
        强制释放锁（无论持有者是谁）。
        慎用：仅在确认对端机器宕机且无法自行释放时调用。
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM hub_lock WHERE lock_id = 1")
            conn.commit()
            return cur.rowcount > 0
