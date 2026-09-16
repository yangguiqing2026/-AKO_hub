# -*- coding: utf-8 -*-
"""spoke_status 回写单测（2026-09-16）。

背景：architect 的"构思确认待命点"此前只写进 stage JSON，state_aggregator 一律
把工单记 done —— 中控台审批队列（WHERE status IN ('manual_review','deploy_wait')）
永远看不到它。实测 16 张 architect 工单全是 done，其中 4 张自带
human_approval_status=pending。

现在：spoke 在待命点返回 spoke_status=manual_review，终态节点照此写库
（含 queue='manual_review'，与 pending_worker 转人工时的取值一致）。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import master.nodes as nodes  # noqa: E402
from core.hub_db import HubDB  # noqa: E402

TASK_ID = "WO-TEST-20260916-REVIEW"


def _mock_paths(monkeypatch, tmp_path) -> str:
    db_path = str(tmp_path / "age_hub_test.db")
    monkeypatch.setattr(
        nodes,
        "_resolve_hub_paths",
        lambda: {
            "sync_root": str(tmp_path),
            "db_path": db_path,
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        },
    )
    HubDB(db_path).init_schema()
    with HubDB(db_path) as db:
        db.execute(
            "INSERT INTO task_queue (task_id, workflow_id, trigger_agent, status, queue, "
            "submitter, started_at, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
            (TASK_ID, "AKO_architect_agent", "AKO_hub_intake_agent", "running", "main",
             "AKO_hub_intake_agent", "2026-09-16T12:00:00", "{}"),
        )
    return db_path


def _row(db_path: str) -> dict:
    with HubDB(db_path) as db:
        return db.fetchone("SELECT status, queue, error_log FROM task_queue WHERE task_id=?", (TASK_ID,))


def test_spoke_requesting_review_lands_in_approval_queue(monkeypatch, tmp_path) -> None:
    """spoke 请求人工确认 → 工单落 manual_review（中控台审批队列才看得到）。"""
    db_path = _mock_paths(monkeypatch, tmp_path)
    nodes.state_aggregator({
        "task_id": TASK_ID,
        "target_workflow": "AKO_architect_agent",
        "trigger_agent": "AKO_hub_intake_agent",
        "generated_files": [],
        "spoke_output": {
            "output_files": ["stage.json"],
            "summary": "architect 任务 陶粒墙板单层厂房方案设计：待构思确认（已进中控台审批队列）",
            "error": None,
            "spoke_status": "manual_review",
        },
    })
    row = _row(db_path)
    assert row["status"] == "manual_review", row
    assert row["queue"] == "manual_review", row
    assert "待构思确认" in (row["error_log"] or "")


def test_plain_spoke_output_still_done(monkeypatch, tmp_path) -> None:
    """未带 spoke_status 的 spoke（报价/写作等）行为不变：仍然 done。"""
    db_path = _mock_paths(monkeypatch, tmp_path)
    nodes.state_aggregator({
        "task_id": TASK_ID,
        "target_workflow": "AKO_quote_agent",
        "trigger_agent": "AKO_hub_intake_agent",
        "generated_files": ["f1"],
        "spoke_output": {"output_files": ["f1"], "summary": "报价完成", "error": None},
    })
    row = _row(db_path)
    assert row["status"] == "done", row
    assert row["queue"] == "main", row


def test_normalizer_keeps_spoke_status() -> None:
    """回归：_normalize_agent_result 只放行 output_files/summary/error，
    spoke_status 在边界被丢弃 → 实测投递设计任务仍落 done（2026-09-16）。"""
    out = nodes._normalize_agent_result({
        "output_files": ["stage.json"],
        "summary": "待构思确认",
        "error": None,
        "spoke_status": "manual_review",
    })
    assert out["spoke_status"] == "manual_review"
    assert out["output_files"] == ["stage.json"]
    assert out["summary"] == "待构思确认"


def test_normalizer_defaults_spoke_status_when_absent() -> None:
    """普通 spoke（报价/写作）不带该字段 → 归一化后为 None，不误判。"""
    out = nodes._normalize_agent_result({"output_files": [], "summary": "报价完成", "error": None})
    assert out.get("spoke_status") is None


def test_normalize_then_aggregate_lands_in_review(monkeypatch, tmp_path) -> None:
    """整链回归：spoke 原始返回值 → 归一化 → 终态节点 → 落 manual_review。"""
    db_path = _mock_paths(monkeypatch, tmp_path)
    spoke_raw = {
        "output_files": ["stage.json"],
        "summary": "architect 任务 厂房方案设计：待构思确认（已进中控台审批队列）",
        "error": None,
        "spoke_status": "manual_review",
    }
    nodes.state_aggregator({
        "task_id": TASK_ID,
        "target_workflow": "AKO_architect_agent",
        "trigger_agent": "AKO_hub_intake_agent",
        "generated_files": [],
        "spoke_output": nodes._normalize_agent_result(spoke_raw),
    })
    assert _row(db_path)["status"] == "manual_review"


def test_unknown_spoke_status_falls_back_to_done(monkeypatch, tmp_path) -> None:
    """只认白名单状态，未知取值不写脏状态（库有 CHECK 约束，写错会静默失败）。"""
    db_path = _mock_paths(monkeypatch, tmp_path)
    nodes.state_aggregator({
        "task_id": TASK_ID,
        "target_workflow": "AKO_architect_agent",
        "trigger_agent": "AKO_hub_intake_agent",
        "generated_files": [],
        "spoke_output": {"output_files": [], "summary": "x", "error": None, "spoke_status": "bogus"},
    })
    assert _row(db_path)["status"] == "done"


def test_auto_executed_marks_queue_auto(monkeypatch, tmp_path) -> None:
    """自动出图任务：状态仍是 done（图已出、无需审批），但 queue 标成 auto ——
    总控台据此在授权队列里以只读卡显示"任务动作"，满足"图自动出、动作要看得见"。
    """
    db_path = _mock_paths(monkeypatch, tmp_path)
    nodes.state_aggregator({
        "task_id": TASK_ID,
        "target_workflow": "AKO_architect_agent",
        "trigger_agent": "AKO_hub_intake_agent",
        "generated_files": ["img1"],
        "spoke_output": {
            "output_files": ["img1"],
            "summary": "效果图自动生成（任务：生成一张单层厂房效果图）：成功 4/4 张，无需审批",
            "error": None,
            "spoke_status": "auto_executed",
        },
    })
    row = _row(db_path)
    assert row["status"] == "done", row
    assert row["queue"] == "auto", row
    assert "效果图自动生成" in (row["error_log"] or "")
