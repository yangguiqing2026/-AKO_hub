"""
AKO Hub — hub_db 迁移单元测试
test_hub_db_migrate.py: 旧版 task_queue（无 6 新列、CHECK 无 deploy_wait、含 2 行数据）
→ init_schema() → 新列存在、数据保留、CHECK 更新、幂等。
"""

import sys
import sqlite3
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB

NEW_COLS = ["display_cap", "priority", "deadline", "sla_seconds", "submitter", "raw_payload"]


def _create_legacy_task_queue(db_path: str) -> None:
    """手工构造旧版 task_queue：无 6 新列、CHECK 不含 deploy_wait、含 2 行数据。"""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE task_queue (
            task_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            trigger_agent TEXT,
            trigger_type TEXT DEFAULT 'manual',
            payload TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed','cancelled','draft')),
            output_file_ids TEXT,
            error_log TEXT,
            started_at TEXT,
            finished_at TEXT
        );
        INSERT INTO task_queue (task_id, workflow_id, status, payload)
            VALUES ('T-OLD-001', 'AKO_quote_agent', 'done', '{"a":1}');
        INSERT INTO task_queue (task_id, workflow_id, status, payload)
            VALUES ('T-OLD-002', 'AKO_law_agent', 'pending', '{"b":2}');
    """)
    conn.commit()
    conn.close()


def test_migrate_task_queue():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "age_hub.db")
        _create_legacy_task_queue(db_path)

        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.close()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute("PRAGMA table_info(task_queue)").fetchall()}
        for col in NEW_COLS:
            assert col in cols, f"迁移后缺少列: {col}"
        # CHECK 约束已更新
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_queue'"
        ).fetchone()["sql"]
        assert "deploy_wait" in ddl
        # 旧数据保留
        rows = conn.execute("SELECT task_id FROM task_queue ORDER BY task_id").fetchall()
        assert [r["task_id"] for r in rows] == ["T-OLD-001", "T-OLD-002"]
        # 默认值补齐
        row = conn.execute("SELECT priority, submitter FROM task_queue WHERE task_id='T-OLD-001'").fetchone()
        assert row["priority"] == "normal"
        assert row["submitter"] == "external"
        conn.close()
        print("  [PASS] 旧表迁移：新列 + CHECK + 数据保留 + 默认值")


def test_migrate_idempotent():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "age_hub.db")
        _create_legacy_task_queue(db_path)

        db = HubDB(db_path)
        db.connect()
        db.init_schema()
        db.init_schema()  # 重复执行必须幂等
        db.close()

        conn = sqlite3.connect(db_path)
        n = conn.execute("SELECT COUNT(*) AS c FROM task_queue").fetchone()[0]
        assert n == 2
        cols = {r[1] for r in conn.execute("PRAGMA table_info(task_queue)").fetchall()}
        # 列数量不因重复迁移而膨胀
        assert len(cols) == 16
        conn.close()
        print("  [PASS] 迁移幂等：数据无重复、列数稳定(16)")


if __name__ == "__main__":
    test_migrate_task_queue()
    test_migrate_idempotent()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] hub_db 迁移单元测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
