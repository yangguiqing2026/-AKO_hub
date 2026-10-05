# -*- coding: utf-8 -*-
"""中控台批准 = 放行 + 盖批准章（2026-09-16）。

背景：architect 构思确认待命点现在会把工单落 manual_review（见
test_spoke_status_writeback.py）。批准后 worker 会用同一份 raw_payload 重跑，
若载荷里不带批准标记，spoke 会**再次**停在待命点 —— 工单在审批队列里循环。
故批准动作除改状态外，还要把 human_confirmed 写进 raw_payload。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dashboard.app as app_mod  # noqa: E402
from core.hub_db import HubDB  # noqa: E402

TASK_ID = "WO-TEST-20260916-APPROVE"


def _seed(monkeypatch, tmp_path) -> str:
    db_path = str(tmp_path / "age_hub_test.db")
    monkeypatch.setattr(
        app_mod,
        "_resolve_paths",
        lambda: {"sync_root": str(tmp_path), "db_path": db_path,
                 "chroma_root": str(tmp_path / "chroma"), "file_root": str(tmp_path / "files")},
    )
    HubDB(db_path).init_schema()
    with HubDB(db_path) as db:
        db.execute(
            "INSERT INTO task_queue (task_id, workflow_id, trigger_agent, status, queue, "
            "submitter, started_at, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
            (TASK_ID, "AKO_architect_agent", "AKO_hub_intake_agent", "manual_review",
             "manual_review", "AKO_hub_intake_agent", "2026-09-16T12:00:00",
             json.dumps({"wo_number": TASK_ID, "module": "AKO_architect_agent",
                         "action": "方案设计", "intent": "陶粒墙板单层厂房方案设计"})),
        )
    return db_path


def _row(db_path: str) -> dict:
    with HubDB(db_path) as db:
        return db.fetchone("SELECT status, queue, raw_payload FROM task_queue WHERE task_id=?", (TASK_ID,))


def test_approve_sets_confirmation_flag_in_payload(monkeypatch, tmp_path) -> None:
    """批准 → status=pending，且载荷带 human_confirmed=true（重跑不再停在待命点）。"""
    db_path = _seed(monkeypatch, tmp_path)
    result = app_mod._review_transition(TASK_ID, "pending", "")
    assert result.get("status") == "ok", result

    row = _row(db_path)
    assert row["status"] == "pending"
    payload = json.loads(row["raw_payload"])
    assert payload.get("human_confirmed") is True
    # 原有载荷字段不能被覆盖丢
    assert payload.get("intent") == "陶粒墙板单层厂房方案设计"


def test_reject_does_not_set_confirmation_flag(monkeypatch, tmp_path) -> None:
    """拒绝 → failed，且不得盖批准章。"""
    db_path = _seed(monkeypatch, tmp_path)
    result = app_mod._review_transition(TASK_ID, "failed", "治理者拒绝")
    assert result.get("status") == "ok", result

    row = _row(db_path)
    assert row["status"] == "failed"
    assert json.loads(row["raw_payload"]).get("human_confirmed") is None


def test_approve_outside_queue_is_refused(monkeypatch, tmp_path) -> None:
    """不在人工评审队列的工单不可批准，且不被盖上批准章。"""
    db_path = _seed(monkeypatch, tmp_path)
    with HubDB(db_path) as db:
        db.execute("UPDATE task_queue SET status='done' WHERE task_id=?", (TASK_ID,))
    result = app_mod._review_transition(TASK_ID, "pending", "")
    assert result.get("status") == "fail", result
    row = _row(db_path)
    assert row["status"] == "done"
    assert json.loads(row["raw_payload"]).get("human_confirmed") is None
