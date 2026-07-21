"""
AKO Hub — 元数据库管理模块
Hub_DB: SQLite 单文件封装，负责建表、连接、备份与基础 CRUD。

文档编号: AGE-TECH-AKO-HUB-001
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


# ── 建表 SQL（与白皮书 3.3 节严格一致） ──────────────────────────

SCHEMA_SQL = """
-- 知识库注册表
CREATE TABLE IF NOT EXISTS knowledge_base (
    kb_id TEXT PRIMARY KEY,
    kb_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    collection_name TEXT NOT NULL UNIQUE,
    embedding_model TEXT DEFAULT 'bge-m3',
    vector_db_path TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 文件产出注册表
CREATE TABLE IF NOT EXISTS file_registry (
    file_id TEXT PRIMARY KEY,
    source_agent TEXT NOT NULL,
    source_node TEXT,
    rel_path TEXT NOT NULL,
    abs_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    project_tag TEXT NOT NULL,
    version_tag TEXT DEFAULT 'v0.1',
    file_hash TEXT,
    file_size INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    is_synced INTEGER DEFAULT 0,
    sync_verified_at TEXT
);

-- 任务流水表
CREATE TABLE IF NOT EXISTS task_queue (
    task_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    trigger_agent TEXT,
    trigger_type TEXT DEFAULT 'manual',
    payload TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed','cancelled')),
    output_file_ids TEXT,
    error_log TEXT,
    started_at TEXT,
    finished_at TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_file_project ON file_registry(project_tag);
CREATE INDEX IF NOT EXISTS idx_file_agent ON file_registry(source_agent);
CREATE INDEX IF NOT EXISTS idx_file_type ON file_registry(file_type);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_kb_agent ON knowledge_base(agent_name);

-- 同步日志表（P2 阶段启用，P0 预建）
CREATE TABLE IF NOT EXISTS sync_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    peer_hash TEXT,
    local_hash TEXT,
    status TEXT NOT NULL CHECK(status IN ('match','mismatch','missing')),
    checked_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


class HubDB:
    """
    SQLite 元数据库封装。

    约束：
    - 单文件，必须位于百度云盘同步目录内，确保双机一致。
    - 禁止存储大文件二进制，仅存储路径与元数据。
    - 所有时间戳使用 ISO 8601 本地时间（sqlite datetime('now', 'localtime')）。
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self._conn: Optional[sqlite3.Connection] = None

    # ── 连接与初始化 ──────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """建立连接并启用外键与 WAL 模式。"""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL 模式提升并发，且兼容百度云盘同步（单文件仍然只有 .db 会被同步，
        # -wal / -shm 为临时文件，同步软件通常忽略即可，关闭连接后自动合并）
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_schema(self) -> None:
        """首次部署时执行建表与索引。幂等：可重复执行。"""
        if self._conn is None:
            self.connect()
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        """关闭连接，WAL 日志合并到主库。"""
        if self._conn:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None

    # ── 备份 ───────────────────────────────────────────────────────

    def backup(self, backup_dir: str | Path) -> Path:
        """
        将当前 .db 复制到备份目录，命名格式：
            age_hub_YYYYMMDD_HHMMSS.db
        保留最近 30 份，超期自动删除。
        """
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"age_hub_{ts}.db"
        backup_path = backup_dir / backup_name

        shutil.copy2(str(self.db_path), str(backup_path))

        # 清理超期备份（保留最近 30 份）
        backups = sorted(
            backup_dir.glob("age_hub_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[30:]:
            old.unlink()

        return backup_path

    # ── 辅助 ───────────────────────────────────────────────────────

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """底层执行，便于扩展。"""
        if self._conn is None:
            self.connect()
        return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, seq: List[tuple]) -> sqlite3.Cursor:
        if self._conn is None:
            self.connect()
        return self._conn.executemany(sql, seq)

    def commit(self) -> None:
        if self._conn:
            self._conn.commit()

    def fetchall(self, sql: str, parameters: tuple = ()) -> List[Dict[str, Any]]:
        """以字典列表返回查询结果。"""
        cur = self.execute(sql, parameters)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def fetchone(self, sql: str, parameters: tuple = ()) -> Optional[Dict[str, Any]]:
        cur = self.execute(sql, parameters)
        row = cur.fetchone()
        return dict(row) if row else None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self.commit()
        self.close()
        return False
