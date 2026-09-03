# -*- coding: utf-8 -*-
"""批2 L0 注册级测试（2026-09-03 口径：GUI/工具型仅看板可见，禁止 hub 调度）。

8 个：chart/art/web_consult（GUI）+ git_push/pack/pipeline/file_tag_manager/review_runner（工具）。
固化：
1. 均已注册且 invoke_mode=manual_gui、status=registered、taxonomy 分类齐；
2. task_router 显式调度 manual_gui → 明确拒绝（failed + 提示语）；
3. pending_worker 对 manual_gui 行判定不可路由（转人工，不执行）。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id, list_all_spokes  # noqa: E402
from registry.taxonomy import TAXONOMY  # noqa: E402

L0_IDS = [
    "AKO_chart_agent", "AKO_art_agent", "AKO_web_consult_agent",
    "AKO_git_push_agent", "AKO_pack_agent", "AKO_pipeline_agent",
    "AKO_file_tag_manager_agent", "AKO_review_runner_agent",
]


def test_l0_all_registered_manual_gui():
    for wid in L0_IDS:
        entry = get_spoke_by_id(wid)
        assert entry is not None, f"{wid} 未注册"
        assert entry["invoke_mode"] == "manual_gui", f"{wid}: {entry['invoke_mode']}"
        assert entry["status"] == "registered", wid
        t = TAXONOMY.get(wid, {})
        assert t.get("domain") and t.get("function"), f"{wid} 缺 taxonomy 分类"


def test_router_rejects_explicit_l0_dispatch():
    from master.nodes import task_router

    state = {
        "task_id": "T-L0-TEST",
        "input_payload": {"workflow_id": "AKO_chart_agent"},
    }
    out = task_router(state)
    assert out["status"] == "failed"
    assert "禁止 hub 调度" in out["error_log"], out["error_log"]


def test_router_still_accepts_importlib_spoke():
    from master.nodes import task_router

    state = {"task_id": "T-OK-TEST", "input_payload": {"workflow_id": "AKO_quote_agent"}}
    out = task_router(state)
    assert out["status"] == "pending", out


def test_pending_worker_l0_row_unroutable(tmp_path):
    from core.hub_db import HubDB
    from core.pending_worker import consume_once

    db_path = str(tmp_path / "l0.db")
    HubDB(db_path).init_schema()
    with HubDB(db_path) as db:
        db.execute(
            """INSERT INTO task_queue (task_id, workflow_id, status, submitter, started_at, raw_payload)
               VALUES ('WO-L0-1', 'AKO_chart_agent', 'pending', 'test', '2026-09-03T00:00:00', ?)""",
            (json.dumps({"intent": "画个图"}),),
        )
    stats = consume_once(db_path=db_path, dispatch=lambda t, r: {"status": "done"})
    assert stats["claimed"] == 0 and stats["to_manual"] == 1, stats
