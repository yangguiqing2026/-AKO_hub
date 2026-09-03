# -*- coding: utf-8 -*-
"""批0：intake 工单 HTTP 端点集成测试（进程内起服 + temp DB）。"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import hub_api  # noqa: E402
import hub_http_server  # noqa: E402
from core.hub_db import HubDB  # noqa: E402


class _TestServer:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hub_api, "_resolve_paths", lambda: {
            "sync_root": str(tmp_path),
            "db_path": str(tmp_path / "hub_meta_test.db"),
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        })
        HubDB(str(tmp_path / "hub_meta_test.db")).init_schema()
        self.server = HTTPServer(("127.0.0.1", 0), hub_http_server.HubHTTPHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_wo_http_flow(monkeypatch, tmp_path):
    srv = _TestServer(tmp_path, monkeypatch)
    try:
        status, alloc = srv.post("/api/v1/hub/wo/allocate", {
            "draft_wo_number": "draft-http-1",
            "module": "AKO_media_agent",
            "action": "文案生成",
        })
        assert status == 200 and alloc["status"] == "allocated"
        wo = alloc["formal_wo_number"]

        status, ack = srv.post("/api/v1/hub/wo/deliver", {
            "wo_number": wo, "module": "AKO_media_agent", "action": "文案生成",
        })
        assert status == 200 and ack["status"] == "acknowledged"

        status, q = srv.post("/api/v1/hub/wo/manual_review", {"wo_number": wo})
        assert status == 200 and q["queue"] == "manual_review"

        status, row = srv.get(f"/api/v1/hub/wo/{wo}")
        assert status == 200 and row["status"] == "manual_review"
    finally:
        srv.close()


def test_wo_http_missing_draft_400(monkeypatch, tmp_path):
    srv = _TestServer(tmp_path, monkeypatch)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/v1/hub/wo/allocate",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("预期 400 未发生")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        srv.close()
