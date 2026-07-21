"""
AKO Hub — Master Graph 运行器（P2 扩展版）
runner.py: 支持 run / sync / status / list-files 子命令。

用法：
    python master/runner.py run --intent "结构计算"
    python master/runner.py sync --project taoli
    python master/runner.py status
    python master/runner.py list-files --project taoli

文档编号: AGE-TECH-AKO-HUB-001 §7.2
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

from master.graph import get_master_graph
from master.state import MasterState
from master.nodes import standalone_sync_check
from core.hub_db import HubDB
from core.file_bus import FileBus
from core.knowledge_hub import KnowledgeHub


def _build_payload(args) -> dict:
    """根据 CLI 参数构建 input_payload。"""
    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"raw_input": args.payload}
    if args.intent:
        payload["intent"] = args.intent
    if args.workflow:
        payload["workflow_id"] = args.workflow
    if args.project:
        payload["project_tag"] = args.project
    return payload


def _resolve_paths():
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        root = Path(cfg["sync_root"]).resolve()
        return {
            "sync_root": str(root),
            "db_path": str(root / cfg.get("meta_db", "age_hub.db")),
            "chroma_root": str(root / cfg.get("chroma_root", "chroma_db")),
            "file_root": str(root / cfg.get("file_root", "files")),
        }
    except Exception as e:
        # 如果配置文件读取失败，使用默认路径
        default_root = Path(__file__).resolve().parent.parent
        return {
            "sync_root": str(default_root),
            "db_path": str(default_root / "age_hub.db"),
            "chroma_root": str(default_root / "chroma_db"),
            "file_root": str(default_root / "files"),
        }


def cmd_run(args) -> None:
    """执行单个 Master Graph 任务。"""
    graph = get_master_graph()
    payload = _build_payload(args)
    task_id = args.task_id or f"T-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"[TASK] {task_id}")
    print(f"  payload: {payload}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    initial_state: MasterState = {
        "task_id": task_id,
        "target_workflow": "",
        "target_agent": None,
        "input_payload": payload,
        "required_kb_ids": [],
        "output_dir": None,
        "generated_files": [],
        "output_summary": None,
        "status": "pending",
        "error_log": None,
        "retry_count": 0,
        "max_retry": 3,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "kb_status": None,
        "sync_status": None,
        "spoke_output_paths": [],
    }

    try:
        result = graph.invoke(initial_state)
        result_dict = dict(result)
    except Exception as e:
        result_dict = {
            "task_id": task_id,
            "status": "failed",
            "error_log": f"Master Graph 异常: {type(e).__name__}: {e}",
            "finished_at": datetime.now().isoformat(),
        }

    print(f"\n[RESULT] status: {result_dict.get('status')}")
    if result_dict.get("output_summary"):
        print(f"  summary: {result_dict['output_summary']}")
    if result_dict.get("generated_files"):
        print(f"  files: {len(result_dict['generated_files'])} 个")
        for fid in result_dict["generated_files"][:5]:
            print(f"    - {fid}")
    if result_dict.get("error_log"):
        print(f"  error: {result_dict['error_log']}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def cmd_sync(args) -> None:
    """执行同步校验。"""
    project = args.project or ""
    print(f"[SYNC] 开始同步校验: project={project or '全部'}")
    result = standalone_sync_check(project_tag=project)
    print(f"\n{result['sync_summary']}")
    if args.verbose and result["sync_results"].get("details"):
        for d in result["sync_results"]["details"][:20]:
            print(f"  {d['file_id']}: {d['status']}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def cmd_status(args) -> None:
    """查询全局状态统计。"""
    paths = _resolve_paths()

    with HubDB(paths["db_path"]) as db:
        tasks = db.fetchall("SELECT status, COUNT(*) as cnt FROM task_queue GROUP BY status")
        files = db.fetchall("SELECT is_synced, COUNT(*) as cnt FROM file_registry GROUP BY is_synced")
        kbs = db.fetchall("SELECT COUNT(*) as cnt FROM knowledge_base")

    print("[STATUS] AKO Hub 全局统计")
    print(f"\n  任务队列:")
    for t in tasks:
        print(f"    {t['status']}: {t['cnt']} 个")

    print(f"\n  文件注册:")
    for f in files:
        label = {0: "未校验", 1: "已同步", 2: "冲突"}.get(f["is_synced"], "未知")
        print(f"    {label}: {f['cnt']} 个")

    print(f"\n  知识库: {kbs[0]['cnt'] if kbs else 0} 个")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def cmd_list_files(args) -> None:
    """列出文件。"""
    paths = _resolve_paths()
    bus = FileBus(paths["db_path"], paths["file_root"])

    project = args.project
    agent = args.agent
    file_type = args.file_type

    if project:
        rows = bus.find_by_project(project, file_type)
    elif agent:
        rows = bus.find_by_agent(agent, project)
    else:
        with HubDB(paths["db_path"]) as db:
            rows = db.fetchall("SELECT * FROM file_registry ORDER BY created_at DESC LIMIT 50")

    print(f"[FILES] 共 {len(rows)} 个文件")
    for r in rows[:20]:
        sync_label = {0: "未校验", 1: "已同步", 2: "冲突"}.get(r.get("is_synced", 0), "未知")
        print(f"  {r['file_id']} | {r['project_tag']} | {r['file_type']} | {sync_label} | {r['rel_path']}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def main():
    parser = argparse.ArgumentParser(description="AKO Hub Master Graph 运行器 (P2)")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser("run", help="执行 Master Graph 任务")
    run_p.add_argument("--task-id", default=None, help="任务 ID")
    run_p.add_argument("--intent", default="", help="任务意图")
    run_p.add_argument("--workflow", default="", help="显式 workflow_id")
    run_p.add_argument("--project", default="", help="项目标签")
    run_p.add_argument("--payload", default="", help="JSON 输入参数")
    run_p.add_argument("--trigger", default="manual", help="触发源")

    # sync
    sync_p = sub.add_parser("sync", help="执行文件同步校验")
    sync_p.add_argument("--project", default="", help="项目标签")
    sync_p.add_argument("--verbose", action="store_true", help="显示详细结果")

    # status
    sub.add_parser("status", help="查询全局状态统计")

    # list-files
    lf_p = sub.add_parser("list-files", help="列出注册文件")
    lf_p.add_argument("--project", default="", help="项目标签")
    lf_p.add_argument("--agent", default="", help="Agent 名称")
    lf_p.add_argument("--file-type", default="", help="文件类型")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "list-files":
        cmd_list_files(args)


if __name__ == "__main__":
    main()
