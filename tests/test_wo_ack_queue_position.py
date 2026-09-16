# -*- coding: utf-8 -*-
"""queue_position 语义回归（2026-09-16）。

背景：`_wo_ack` 原实现取「全表 status='pending' 计数」，且在自己落库之后统计，
空闲系统投递一张单也报 1 —— 前端 taskProgress 把它读成「前面还有 N 个」，
于是每次投递都提示「排队中 · 前面还有 1 个」，那个 1 是任务自己。

新语义：**同队列中排在自己前面的 pending 数（不含自己）**，空闲时为 0。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import hub_api  # noqa: E402
from core.hub_db import HubDB  # noqa: E402


def _patch_paths(monkeypatch, tmp_path) -> str:
    def fake_resolve():
        return {
            "sync_root": str(tmp_path),
            "db_path": str(tmp_path / "hub_meta_test.db"),
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        }

    monkeypatch.setattr(hub_api, "_resolve_paths", fake_resolve)
    db_path = str(tmp_path / "hub_meta_test.db")
    HubDB(db_path).init_schema()
    return db_path


def _deliver(wo_number: str, module: str = "AKO_quote_agent") -> dict:
    return hub_api.deliver_wo(
        {"wo_number": wo_number, "module": module, "action": "报价"}
    )


def test_idle_system_reports_no_one_ahead(monkeypatch, tmp_path):
    """空闲系统投递一张单：前面没人 → 0（原 bug 报 1，那个 1 是自己）。"""
    _patch_paths(monkeypatch, tmp_path)
    ack = _deliver("WO-T-001")
    assert ack["queue_position"] == 0


def test_pending_task_in_same_queue_counts_as_ahead(monkeypatch, tmp_path):
    """同队列已有一张 pending：第一张 0，第二张 1（前者确实排在前面）。"""
    _patch_paths(monkeypatch, tmp_path)
    first = _deliver("WO-T-002")
    second = _deliver("WO-T-003")
    assert first["queue_position"] == 0
    assert second["queue_position"] == 1


def test_pending_task_in_other_queue_not_counted(monkeypatch, tmp_path):
    """别的队列有 pending 不算在自己头上（口径按队列收窄）→ 0。"""
    db_path = _patch_paths(monkeypatch, tmp_path)
    with HubDB(db_path) as db:
        db.execute(
            "INSERT INTO task_queue "
            "(task_id, workflow_id, status, queue, submitter, started_at, raw_payload) "
            "VALUES (?, ?, 'pending', 'other_queue', 'test', ?, '{}')",
            ("WO-OTHER-001", "AKO_other_agent", "2026-09-16T00:00:00"),
        )
    ack = _deliver("WO-T-004")
    assert ack["queue_position"] == 0
