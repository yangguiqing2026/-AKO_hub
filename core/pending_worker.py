# -*- coding: utf-8 -*-
"""
core/pending_worker.py — pending 队列消费 Worker（体系级断点补齐，2026-09-03 批）

背景：intake/工单 deliver 将正式工单入队 status='pending'，但此前没有任何消费循环
执行 pending → 历史 pending 长期滞留（8-27 起 5 条）。本模块补上消费循环。

设计（经 AKO_studio 拍板，2026-09-03）：
1. 认领式消费：先把 pending 行 UPDATE 为 running（认领，防双 worker 重复执行），
   再执行；图收尾节点按 task_id upsert 回写 done/failed（复用现有 master graph 语义）。
2. 只消费"可路由"行：status=pending 且 workflow_id 已注册（registered/active）
   且 raw_payload 可解析并含 intent 或 workflow_id。不可路由 → 转 manual_review
   人工审核队列（error_log 注明原因），不硬跑、不死循环。
3. draft / manual_review / deploy_wait / running 状态一律不碰。
4. run_loop 以守护线程形式挂进 hub_http_server(:8080) 进程，随其生命周期；
   env AKO_HUB_WORKER=0 可禁用（测试/排障用）。

注：工作流 caller 内部自带分布式锁（core/distributed_lock），双机场景由该锁串行化。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pending_worker")

DEFAULT_INTERVAL = 10.0  # 秒


def _hub_db_path() -> str:
    """读取 config/hub.yaml 得到 meta_db 绝对路径（与 hub_api._resolve_paths 一致）。"""
    try:
        import yaml

        cfg_path = Path(__file__).resolve().parent.parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        root = Path(cfg["sync_root"]).resolve()
        return str(root / cfg.get("meta_db", "age_hub.db"))
    except Exception:
        return str(Path(__file__).resolve().parent.parent / "hub_meta.db")


def _is_registered(workflow_id: str) -> bool:
    """workflow 已注册且非 deprecated。"""
    try:
        from registry.workflows import get_spoke_by_id

        entry = get_spoke_by_id(workflow_id)
        return bool(entry) and entry.get("status") in ("registered", "active")
    except Exception:
        return False


def is_routable(row: Dict[str, Any]) -> bool:
    """
    可路由判定：status=pending 且 workflow 已注册且 raw_payload 可解析出
    intent 或 workflow_id（至少一个）。解析失败的 payload 视为不可路由。
    """
    if row.get("status") != "pending":
        return False
    workflow_id = str(row.get("workflow_id", "")).strip()
    if not workflow_id or not _is_registered(workflow_id):
        return False
    try:
        from registry.workflows import get_spoke_by_id

        if get_spoke_by_id(workflow_id).get("invoke_mode") == "manual_gui":
            return False  # L0 注册级（GUI/工具型）不参与队列调度
    except Exception:
        pass
    raw = row.get("raw_payload")
    if not raw:
        return False
    try:
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    # 路由依据：intent / 显式 workflow_id / action（intake deliver 载荷为 module+action，无 intent）
    return bool(
        str(payload.get("intent", "")).strip()
        or str(payload.get("workflow_id", "")).strip()
        or str(payload.get("action", "")).strip()
    )


def default_dispatch(task_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """真实派发：以 pending 行 task_id 走 master graph（收尾节点按 task_id upsert 回写）。"""
    import hub_api

    payload = json.loads(row["raw_payload"]) if isinstance(row["raw_payload"], str) else (row["raw_payload"] or {})
    payload.setdefault("workflow_id", row.get("workflow_id", ""))
    return hub_api.submit_task(
        task_id=task_id,
        payload=payload,
        trigger=str(row.get("submitter") or "pending_worker"),
    )


def _claim_and_run(db_path: str, row: Dict[str, Any], dispatch: Callable) -> Dict[str, Any]:
    """认领（pending→running）后派发；执行结果由图/派发方落库，认领失败返回 None。"""
    from core.hub_db import HubDB

    task_id = str(row["task_id"])
    with HubDB(db_path) as db:
        cur = db.execute(
            "UPDATE task_queue SET status='running' WHERE task_id=? AND status='pending'",
            (task_id,),
        )
        if cur.rowcount == 0:
            return {"status": "skipped", "reason": "已被其他 worker 认领"}
    return dispatch(task_id, row)


def consume_once(
    db_path: Optional[str] = None,
    dispatch: Optional[Callable] = None,
    max_rows: int = 8,
) -> Dict[str, Any]:
    """单轮消费：扫描 pending → 认领 → 派发/转人工。返回统计。"""
    from core.hub_db import HubDB

    db_path = db_path or _hub_db_path()
    dispatch = dispatch or default_dispatch
    stats: Dict[str, int] = {"scanned": 0, "claimed": 0, "done": 0, "failed": 0, "to_manual": 0}

    with HubDB(db_path) as db:
        rows = db.fetchall(
            "SELECT task_id, workflow_id, status, submitter, raw_payload "
            "FROM task_queue WHERE status='pending' "
            "ORDER BY started_at ASC LIMIT ?",
            (max_rows,),
        )
    stats["scanned"] = len(rows)

    for row in rows:
        task_id = str(row["task_id"])
        if not is_routable(row):
            # 不可路由 → 人工审核队列（不清除、不硬跑）
            try:
                from core.hub_db import HubDB

                reason = "pending_worker: 不可路由（workflow 未注册或 raw_payload 无 intent/workflow_id），转人工核查"
                with HubDB(db_path) as db:
                    db.execute(
                        "UPDATE task_queue SET status='manual_review', queue='manual_review', error_log=? WHERE task_id=? AND status='pending'",
                        (reason, task_id),
                    )
                stats["to_manual"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("转人工失败 %s: %s", task_id, exc)
            continue

        try:
            result = _claim_and_run(db_path, row, dispatch)
            outcome = (result or {}).get("status", "")
            if outcome == "failed":
                stats["failed"] += 1
            elif outcome == "skipped":
                pass  # 他方认领，不计
            else:
                stats["done"] += 1
            stats["claimed"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("派发异常 %s: %s", task_id, exc)
            stats["failed"] += 1

    return stats


def run_loop(
    interval: float = DEFAULT_INTERVAL,
    stop_event: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> None:
    """轮询循环（守护线程入口）。stop_event.is_set() 为 True 时退出。"""
    logger.info("pending_worker 启动：interval=%.0fs db=%s", interval, db_path or _hub_db_path())
    while not (stop_event and stop_event.is_set()):
        try:
            stats = consume_once(db_path=db_path)
            if any(stats.values()):
                logger.info("consume 轮次: %s", stats)
        except Exception as exc:  # noqa: BLE001
            logger.error("consume 轮次异常: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="pending 队列单轮消费（诊断/排障用）")
    parser.add_argument("--once", action="store_true", help="只消费一轮后退出")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.once:
        print("stats:", consume_once())
    else:
        run_loop()
