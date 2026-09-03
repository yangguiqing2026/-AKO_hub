# -*- coding: utf-8 -*-
"""批补：pending 消费 worker 单元测试（temp DB + 注入假派发，不触真实 agent/图）。

编排层单测（认领/可路由/回写语义）；真实 master graph 派发路径由生产联调覆盖
（logs/deploy_acceptance_20260903.md P1-P5 同款链路）。
"""
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB  # noqa: E402
from core.pending_worker import consume_once, is_routable  # noqa: E402


def _seed(db_path, rows):
    with HubDB(db_path) as db:
        for r in rows:
            db.execute(
                """INSERT INTO task_queue
                   (task_id, workflow_id, status, submitter, started_at, raw_payload)
                   VALUES (?,?,?,?,?,?)""",
                (
                    r["task_id"],
                    r.get("workflow_id", "AKO_quote_agent"),
                    r.get("status", "pending"),
                    r.get("submitter", "test"),
                    r.get("started_at", "2026-09-03T00:00:00"),
                    r.get("raw_payload"),
                ),
            )


def _make_db(tmp_path):
    db_path = str(tmp_path / "worker_test.db")
    HubDB(db_path).init_schema()
    return db_path


def test_routable_pending_dispatched(tmp_path):
    db_path = _make_db(tmp_path)
    _seed(db_path, [{
        "task_id": "WO-T1",
        "raw_payload": json.dumps({"intent": "报价: 100㎡内墙150mm"}, ensure_ascii=False),
    }])
    calls = {}

    def fake_dispatch(task_id, row):
        calls["task_id"] = task_id
        return {"status": "done"}

    stats = consume_once(db_path=db_path, dispatch=fake_dispatch)
    assert stats == {"scanned": 1, "claimed": 1, "done": 1, "failed": 0, "to_manual": 0}
    assert calls["task_id"] == "WO-T1"
    # 认领后状态为 running（图收尾节点在真实路径负责回写 done）
    with HubDB(db_path) as db:
        row = db.fetchone("SELECT status FROM task_queue WHERE task_id='WO-T1'")
        assert row["status"] == "running"


def test_deliver_style_action_payload_routable(tmp_path):
    """intake deliver 载荷（module+action 无 intent）视为可路由。"""
    db_path = _make_db(tmp_path)
    _seed(db_path, [{
        "task_id": "WO-T2",
        "raw_payload": json.dumps({"wo_number": "WO-T2", "module": "AKO_quote_agent", "action": "生成报价"}, ensure_ascii=False),
    }])
    stats = consume_once(db_path=db_path, dispatch=lambda t, r: {"status": "done"})
    assert stats["done"] == 1, stats


def test_unroutable_goes_manual_review(tmp_path):
    """历史 pending（无 raw_payload）→ 转人工审核队列，不硬跑、不清除。"""
    db_path = _make_db(tmp_path)
    _seed(db_path, [{"task_id": "WO-LEGACY", "raw_payload": None}])
    stats = consume_once(db_path=db_path, dispatch=lambda t, r: {"status": "done"})
    assert stats == {"scanned": 1, "claimed": 0, "done": 0, "failed": 0, "to_manual": 1}
    with HubDB(db_path) as db:
        row = db.fetchone("SELECT status, queue, error_log FROM task_queue WHERE task_id='WO-LEGACY'")
        assert row["status"] == "manual_review"
        assert row["queue"] == "manual_review"
        assert "不可路由" in row["error_log"]


def test_draft_and_manual_review_untouched(tmp_path):
    db_path = _make_db(tmp_path)
    _seed(db_path, [
        {"task_id": "WO-D", "status": "draft", "raw_payload": "{}"},
        {"task_id": "WO-M", "status": "manual_review", "raw_payload": "{}"},
    ])
    stats = consume_once(db_path=db_path, dispatch=lambda t, r: {"status": "done"})
    assert stats == {"scanned": 0, "claimed": 0, "done": 0, "failed": 0, "to_manual": 0}
    with HubDB(db_path) as db:
        assert db.fetchone("SELECT status FROM task_queue WHERE task_id='WO-D'")["status"] == "draft"
        assert db.fetchone("SELECT status FROM task_queue WHERE task_id='WO-M'")["status"] == "manual_review"


def test_claimed_row_not_double_run(tmp_path):
    """已处于 running 的行不会被再次认领。"""
    db_path = _make_db(tmp_path)
    _seed(db_path, [{"task_id": "WO-R", "status": "running", "raw_payload": json.dumps({"intent": "x"})}])
    stats = consume_once(db_path=db_path, dispatch=lambda t, r: {"status": "done"})
    assert stats["claimed"] == 0


def test_is_routable_edge_cases(tmp_path):
    _make_db(tmp_path)
    base = {"task_id": "X", "status": "pending", "workflow_id": "AKO_quote_agent"}
    assert is_routable({**base, "raw_payload": json.dumps({"intent": "报价"})})
    assert is_routable({**base, "raw_payload": json.dumps({"action": "生成报价"})})
    assert not is_routable({**base, "raw_payload": None})
    assert not is_routable({**base, "raw_payload": "not-json"})
    assert not is_routable({**base, "raw_payload": "{}", "status": "draft"})
    assert not is_routable({**base, "raw_payload": json.dumps({"intent": "报价"}), "workflow_id": "AKO_no_such"})
