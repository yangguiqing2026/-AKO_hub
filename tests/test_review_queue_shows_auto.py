# -*- coding: utf-8 -*-
"""总控台授权队列：自动出图任务可见（2026-09-16）。

AKO_studio 口径：自动出图 = 图片生成自动，但**任务动作要在总控台看得见**。
实现：自动出图的工单终态标 queue='auto'（不占审批位），授权队列接口把最近
这类任务一并返回、标记 auto_executed，前端渲染为只读卡（无批准/拒绝按钮）。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dashboard.app as app_mod  # noqa: E402
from core.hub_db import HubDB  # noqa: E402

AUTO_ID = "WO-TEST-20260916-AUTO"
REVIEW_ID = "WO-TEST-20260916-WAIT"


def _seed(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "age_hub_q.db")
    monkeypatch.setattr(
        app_mod,
        "_resolve_paths",
        lambda: {"sync_root": str(tmp_path), "db_path": db_path,
                 "chroma_root": str(tmp_path / "chroma"), "file_root": str(tmp_path / "files")},
    )
    HubDB(db_path).init_schema()
    with HubDB(db_path) as db:
        for tid, status, queue, action in (
            (AUTO_ID, "done", "auto", "生成一张单层厂房效果图"),
            (REVIEW_ID, "manual_review", "manual_review", "陶粒墙板单层厂房方案设计"),
        ):
            db.execute(
                "INSERT INTO task_queue (task_id, workflow_id, trigger_agent, status, queue, "
                "submitter, started_at, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                (tid, "AKO_architect_agent", "AKO_hub_intake_agent", status, queue,
                 "AKO_hub_intake_agent", "2026-09-16T13:00:00",
                 json.dumps({"wo_number": tid, "action": action}, ensure_ascii=False)),
            )


def _rows() -> dict:
    return {r["task_id"]: r for r in app_mod._review_rows()}


def test_queue_includes_auto_executed_render_task(monkeypatch, tmp_path) -> None:
    """自动出图的工单出现在授权队列（只读卡），且带任务动作。"""
    _seed(monkeypatch, tmp_path)
    rows = _rows()
    assert AUTO_ID in rows, rows.keys()
    auto = rows[AUTO_ID]
    assert auto["status"] == "auto_executed"
    # 任务动作可见：_payload_summary 从载荷取 action，卡片标题显示的就是它
    assert "单层厂房效果图" in (auto.get("summary") or "")


def test_queue_still_lists_pending_review(monkeypatch, tmp_path) -> None:
    """审批在途的单不受影响，仍是 manual_review（有按钮那种）。"""
    _seed(monkeypatch, tmp_path)
    rows = _rows()
    assert rows[REVIEW_ID]["status"] == "manual_review"


# ── 卡片要显示"任务是什么"，不是通用动词 ──────────────────────────────
# 实测：效果图工单卡片的标题显示成"生成"（action 是 NLU 的通用动词），
# 真正表达任务的是大门透传的 intent/raw_input/topic。用户口径是
# "任务动作要在总控台看得见"，故摘要必须优先取需求原文。

def test_summary_prefers_task_text_over_generic_action(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path)
    with HubDB(str(tmp_path / "age_hub_q.db")) as db:
        db.execute(
            "UPDATE task_queue SET raw_payload=? WHERE task_id=?",
            (json.dumps({
                "wo_number": AUTO_ID,
                "action": "生成",
                "intent": "生成一张单层厂房效果图，要能看到建筑全貌。",
            }, ensure_ascii=False), AUTO_ID),
        )
    row = _rows()[AUTO_ID]
    assert "单层厂房效果图" in (row["summary"] or ""), row
    assert row["summary"] != "生成"
    # action 字段本身仍保留原始动作（前端另有用途）
    assert row["action"] == "生成"


def test_summary_falls_back_to_action_when_no_text(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path)
    row = _rows()[REVIEW_ID]
    assert row["summary"] == "陶粒墙板单层厂房方案设计"


def test_queue_orders_newest_first_across_kinds(monkeypatch, tmp_path) -> None:
    """面板只渲染前 4 张卡（governor.html q.slice(0,4)）—— 新任务必须排在旧待审前面，
    否则今天的生图卡会被一堆历史 manual_review 挤到面板之外（实测不可见）。"""
    _seed(monkeypatch, tmp_path)
    db_path = str(tmp_path / "age_hub_q.db")
    with HubDB(db_path) as db:
        db.execute("UPDATE task_queue SET started_at='2026-09-09T08:00:00' WHERE task_id=?", (REVIEW_ID,))
        db.execute("UPDATE task_queue SET started_at='2026-09-16T16:20:00' WHERE task_id=?", (AUTO_ID,))
    rows = app_mod._review_rows()
    assert rows[0]["task_id"] == AUTO_ID, [r["task_id"] for r in rows]
