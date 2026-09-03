# -*- coding: utf-8 -*-
"""批0：intake 工单 API 单元测试（temp DB，monkeypatch _resolve_paths）。"""
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import hub_api  # noqa: E402
from core.hub_db import HubDB  # noqa: E402


def _patch_paths(monkeypatch, tmp_path):
    def fake_resolve():
        return {
            "sync_root": str(tmp_path),
            "db_path": str(tmp_path / "hub_meta_test.db"),
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        }
    monkeypatch.setattr(hub_api, "_resolve_paths", fake_resolve)
    # 预建库（含在途迁移：manual_review 状态 + queue/draft_wo_number 列）
    HubDB(str(tmp_path / "hub_meta_test.db")).init_schema()
    return tmp_path


def test_allocate_generates_wo_and_idempotent(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    today = datetime.now().strftime("%Y%m%d")
    first = hub_api.allocate_wo("draft-A", "AKO_quote_agent", "生成报价")
    assert first["status"] == "allocated"
    assert first["formal_wo_number"] == f"WO-HAI-{today}-001"
    assert first["idempotent"] is False

    again = hub_api.allocate_wo("draft-A", "AKO_quote_agent", "生成报价")
    assert again["formal_wo_number"] == first["formal_wo_number"]
    assert again["idempotent"] is True


def test_deliver_wo_pending_and_ack(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    wo = hub_api.allocate_wo("draft-B", "AKO_law_agent", "合规预检")
    ack = hub_api.deliver_wo({
        "wo_number": wo["formal_wo_number"],
        "module": "AKO_law_agent",
        "action": "合规预检",
        "scope": "test",
    })
    assert ack["status"] == "acknowledged"
    assert ack["wo_number"] == wo["formal_wo_number"]
    assert isinstance(ack["queue_position"], int)

    row = hub_api.get_wo_status(wo["formal_wo_number"])
    assert row["status"] == "pending"
    assert row["queue"] == "main"
    assert row["draft_wo_number"] == "draft-B"


def test_manual_review_and_status_lookup(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    wo = hub_api.allocate_wo("draft-C", "AKO_quote_agent", "复杂报价")
    r = hub_api.manual_review_wo({"wo_number": wo["formal_wo_number"], "module": "AKO_quote_agent"})
    assert r["status"] == "queued"
    assert r["queue"] == "manual_review"
    row = hub_api.get_wo_status(wo["formal_wo_number"])
    assert row["status"] == "manual_review"
    assert row["queue"] == "manual_review"


def test_status_not_found(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert hub_api.get_wo_status("WO-HAI-20990101-999")["status"] == "not_found"


def test_deliver_missing_wo_number(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert hub_api.deliver_wo({})["status"] == "FAIL"
