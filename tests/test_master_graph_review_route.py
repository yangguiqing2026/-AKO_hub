# -*- coding: utf-8 -*-
"""master graph 整链：spoke 请求人工确认 → 工单落 manual_review（2026-09-16）。

单测各段（归一化、终态节点）都绿，但实链投递设计任务仍落 done —— 说明断点在
图内的某个边界。本测试在进程内跑完整图（假 spoke），把断点钉死在链上。
"""
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import master.nodes as nodes  # noqa: E402
from core.hub_db import HubDB  # noqa: E402

TASK_ID = "WO-TEST-20260916-GRAPH"
SPOKE_ID = "AKO_stub_spoke"
STUB_MODULE = "stub_spoke_module"


def _prepare(monkeypatch, tmp_path, spoke_return: dict) -> str:
    db_path = str(tmp_path / "age_hub_g.db")
    monkeypatch.setattr(
        nodes,
        "_resolve_hub_paths",
        lambda: {
            "sync_root": str(tmp_path),
            "db_path": db_path,
            "chroma_root": str(tmp_path / "chroma"),
            "file_root": str(tmp_path / "files"),
        },
    )
    HubDB(db_path).init_schema()

    # 假 spoke 模块：记录调用，返回注入结果
    mod = types.ModuleType(STUB_MODULE)
    mod.calls = []

    def fake_run(**kwargs):
        mod.calls.append(kwargs)
        return dict(spoke_return)

    mod.run = fake_run
    sys.modules[STUB_MODULE] = mod

    # 假 registry：让路由把 SPOKE_ID 解析到假模块
    monkeypatch.setattr(
        nodes,
        "get_spoke_by_id",
        lambda sid: {
            "spoke_id": sid,
            "spoke_type": "agent",
            "status": "registered",
            "invoke_mode": "importlib",
            "entry_module": STUB_MODULE,
            "entry_function": "run",
            "source_dir": "",
        } if sid == SPOKE_ID else None,
    )
    # 分布式锁在测试里无意义，放行
    import core.distributed_lock as dl
    monkeypatch.setattr(dl.DistributedLock, "try_acquire", lambda self, timeout_seconds=0: True)
    monkeypatch.setattr(dl.DistributedLock, "release", lambda self: None)
    monkeypatch.setattr(dl.DistributedLock, "is_held", lambda self: None)
    return db_path


def _invoke(db_path: str) -> None:
    from master.graph import get_master_graph

    graph = get_master_graph()
    graph.invoke({
        "task_id": TASK_ID,
        "target_workflow": "",
        "target_agent": None,
        "input_payload": {"workflow_id": SPOKE_ID, "project_tag": "taoli"},
        "required_kb_ids": [],
        "output_dir": "",
        "generated_files": [],
        "output_summary": None,
        "status": "pending",
        "error_log": None,
        "retry_count": 0,
        "max_retry": 3,
        "started_at": "2026-09-16T12:00:00",
        "finished_at": None,
        "kb_status": None,
        "sync_status": None,
        "spoke_output_paths": [],
    })


def _row(db_path: str) -> dict:
    with HubDB(db_path) as db:
        return db.fetchone("SELECT status, queue, error_log FROM task_queue WHERE task_id=?", (TASK_ID,))


def test_spoke_review_request_survives_full_graph(monkeypatch, tmp_path) -> None:
    db_path = _prepare(monkeypatch, tmp_path, {
        "output_files": [],
        "summary": "待构思确认（已进中控台审批队列）",
        "error": None,
        "spoke_status": "manual_review",
    })
    _invoke(db_path)
    row = _row(db_path)
    assert row["status"] == "manual_review", row
    assert row["queue"] == "manual_review", row
    assert "待构思确认" in (row["error_log"] or "")


def test_plain_spoke_result_survives_full_graph(monkeypatch, tmp_path) -> None:
    """对照：普通 spoke（不带状态）走完图仍是 done + 自己的 summary。"""
    db_path = _prepare(monkeypatch, tmp_path, {
        "output_files": [], "summary": "报价完成", "error": None,
    })
    _invoke(db_path)
    row = _row(db_path)
    assert row["status"] == "done", row
    assert "报价完成" in (row["error_log"] or "")
