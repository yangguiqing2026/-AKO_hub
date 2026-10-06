# -*- coding: utf-8 -*-
"""端到端管道：工厂大门工单投递 → hub 派发 → architect spoke 落盘（进程内全链，2026-09-09）。

覆盖三段链路：
  1. 大门 intake：POST /api/v1/hub/wo/allocate + /api/v1/hub/wo/deliver
     （载荷按 intake deliver_with_local_queue 生产形态：module/action/scope/intent）
  2. hub：deliver 落 task_queue(pending) → pending_worker 认领 → master graph
     派发（task_router → kb_allocator → workflow_caller importlib →
     agents.ako_architect_adapter）
  3. architect spoke：AKO_HUB_SPOKE_DRYRUN=1 干跑，落 architect_stage_*.json
     → file_collector 注册 → state_aggregator 回写 done → /task/{id}/result 可查

安全约束：全程 temp DB / temp file_root（monkeypatch hub_api._resolve_paths 与
master.nodes.get_config），不碰生产 hub_meta.db；dry-run 不触发任何 LLM/图生 API。
"""

import json
import os
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
from core.knowledge_hub import KnowledgeHub  # noqa: E402


class _TestServer:
    """进程内 HTTP 服务（同 test_intake_wo_http._TestServer 样板）。"""

    def __init__(self):
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


def _install_tmp_paths(monkeypatch, tmp_path):
    """hub_api 与 master.nodes 两套路径解析全部指向临时目录（禁碰生产库）。"""
    paths = {
        "sync_root": str(tmp_path).replace("\\", "/"),
        "db_path": str(tmp_path / "hub_meta_test.db").replace("\\", "/"),
        "chroma_root": str(tmp_path / "chroma_db").replace("\\", "/"),
        "file_root": str(tmp_path / "files").replace("\\", "/"),
    }
    monkeypatch.setattr(hub_api, "_resolve_paths", lambda: paths)

    import master.nodes
    from core.ako_config.settings import AKOConfig

    # 直接覆盖 nodes 路径解析（防御：个别旧测试会覆写 _resolve_hub_paths，
    # 本测试必须自持路径，不受执行顺序影响）
    monkeypatch.setattr(master.nodes, "_resolve_hub_paths", lambda: paths)

    def _test_config():
        yaml_path = tmp_path / "hub.yaml"
        yaml_path.write_text(
            "sync_root: {sr}\n"
            "meta_db: hub_meta_test.db\n"
            "chroma_root: chroma_db\n"
            "file_root: files\n"
            "machine_id: e2e_machine\n".format(sr=str(tmp_path).replace("\\", "/")),
            encoding="utf-8",
        )
        return AKOConfig(hub_yaml_path=str(yaml_path))

    monkeypatch.setattr(master.nodes, "get_config", _test_config)
    # 知识库注册校验在 temp DB 无元数据 → 放行（kb_allocator 只查表不连 Chroma）
    monkeypatch.setattr(KnowledgeHub, "is_kb_registered", lambda self, kb_id: True)

    (tmp_path / "chroma_db").mkdir(exist_ok=True)
    HubDB(paths["db_path"]).init_schema()
    return paths


def test_gate_to_architect_pipeline_e2e(monkeypatch, tmp_path):
    """大门工单 → hub 派发 → architect dry-run 落盘 → 结果接口可查。"""
    paths = _install_tmp_paths(monkeypatch, tmp_path)
    srv = _TestServer()
    try:
        # 1) 大门申请工单号
        status, alloc = srv.post("/api/v1/hub/wo/allocate", {
            "draft_wo_number": "draft-e2e-arch-1",
            "module": "AKO_architect_agent",
            "action": "方案设计",
        })
        assert status == 200 and alloc["status"] == "allocated"
        wo_number = alloc["formal_wo_number"]

        # 2) 大门投递（intake deliver_with_local_queue 生产形态：含 intent 透传）
        status, ack = srv.post("/api/v1/hub/wo/deliver", {
            "wo_number": wo_number,
            "module": "AKO_architect_agent",
            "action": "方案设计",
            "project_name": "陶粒墙板厂房",
            "scope": "陶粒墙板厂房方案设计",
            "rules": [],
            "prohibitions": [],
            "deliverable": "输出执行结果与报告",
            "deadline": "90分钟",
            "intent": "帮我做一个陶粒墙板厂房的方案设计",
        })
        assert status == 200 and ack["status"] == "acknowledged", ack

        # 3) 落库：pending 且 workflow_id 指向 architect
        status, row = srv.get(f"/api/v1/hub/wo/{wo_number}")
        assert status == 200
        assert row["status"] == "pending"
        assert row["workflow_id"] == "AKO_architect_agent"

        # 4) pending_worker 真实派发（master graph 全链，spoke 干跑）
        os.environ["AKO_HUB_SPOKE_DRYRUN"] = "1"
        try:
            from core.pending_worker import consume_once

            stats = consume_once(db_path=paths["db_path"])
        finally:
            os.environ.pop("AKO_HUB_SPOKE_DRYRUN", None)
        assert stats["done"] >= 1, f"派发未完成: {stats}"

        # 5) architect spoke 干跑落盘 stage 文件（file_root/taoli_wallboard/tech_docs）
        stage_dir = tmp_path / "files" / "taoli_wallboard" / "tech_docs"
        stage_files = list(stage_dir.glob("architect_stage_*.json"))
        assert stage_files, f"stage 文件未落盘: {stage_dir}"
        stage = json.loads(stage_files[0].read_text(encoding="utf-8"))
        assert stage["agent"] == "AKO_architect_agent"
        assert stage["mode"] == "dry-run"

        # 6) 大门回显接口：任务结果只读可查（含 file_registry 路径解析）
        status, result = srv.get(f"/api/v1/hub/task/{wo_number}/result")
        assert status == 200, result
        assert result["status"] == "done"
        # 摘要两种形态均可：spoke 摘要透传 或 hub 收尾节点文件注册兜底（既有语义）
        assert ("architect dry-run OK" in result["summary"]) or result["summary"].startswith("完成，注册")
        assert any(Path(f["abs_path"]).exists() for f in result["files"])
    finally:
        srv.close()
