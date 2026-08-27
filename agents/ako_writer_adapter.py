# -*- coding: utf-8 -*-
"""
AKO Hub — AKO_writer_agent 适配器
将 D:\AKO\AKO_writer_agent 包装为 Hub Spoke（技术写作 N0→N1→N2 流水线）。

流程：
  1. 注册 ako_writer 虚拟包（bootstrap 机制，目录名含下划线无法直接作包名）
  2. WriterSpoke.create_task(InputContract) → 异步执行选题/检索/大纲
  3. 轮询 get_task_status 至终态，结果写 hub 输出目录
  4. N2 大纲产出后进入待人工确认（human_approval_status=pending），工单闭环交由人工
"""

import asyncio
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

SOURCE_DIR = Path(r"D:\AKO\AKO_writer_agent")
SHARED_DIR = Path(r"D:\AKO\AKO_shared")  # 统一命名模块（architect/writer 共享）
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 240.0


def _load_bootstrap() -> None:
    """注册 ako_writer 虚拟包（幂等）。"""
    if "ako_writer" in sys.modules:
        return
    for d in (SOURCE_DIR, SHARED_DIR):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    spec = importlib.util.spec_from_file_location("ako_writer_bootstrap", str(SOURCE_DIR / "bootstrap.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


def _run_async(coro):
    return asyncio.run(coro)


def run(
    intent: str = "",
    project_tag: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口：技术写作任务（N0 选题 → N1 检索 → N2 大纲）。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "writer_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        _load_bootstrap()
        from ako_writer.spoke import WriterSpoke
        from ako_writer.models import InputContract, TopicCard
    except Exception as exc:  # noqa: BLE001
        return {"output_files": [], "summary": "",
                "error": f"AKO_writer 导入失败: {exc}。请确认 {SOURCE_DIR} 目录完整。"}

    topic = str(kwargs.get("topic") or intent or "").strip()[:60] or "陶粒墙板技术应用"
    doc_type = str(kwargs.get("doc_type") or "technical_paper")
    audience = str(kwargs.get("audience") or "internal")
    try:
        target_length = int(kwargs.get("target_length") or 2000)
    except (TypeError, ValueError):
        target_length = 2000

    contract = InputContract(
        # writer N0 仅接受 manual/system_event 两种触发源；hub 派发按 manual 透传
        l0_trigger={"source": "manual",
                    "origin_agent": kwargs.get("trigger_agent", "hub"),
                    "priority": kwargs.get("priority", "normal")},
        l1_topic=TopicCard(topic=topic, doc_type=doc_type,
                           target_length=target_length, audience=audience),
    )

    try:
        spoke = WriterSpoke()
        task_id = _run_async(spoke.create_task(contract))
    except Exception as exc:  # noqa: BLE001
        return {"output_files": [], "summary": "",
                "error": f"AKO_writer 任务创建失败: {exc}"}

    # 轮询至终态
    status: Dict[str, Any] = {}
    start = time.time()
    while time.time() - start < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            status = _run_async(spoke.get_task_status(task_id)) or {}
        except Exception:
            continue
        node = status.get("current_node", "")
        approval = status.get("human_approval_status", "")
        error = status.get("error_msg")
        if error:
            break
        if node in ("END", "human_review", "done") or approval in ("pending", "approved"):
            break

    # 结果落盘
    result_file = output_dir / f"writer_task_{task_id}.json"
    result_file.write_text(
        json.dumps({"task_id": task_id, "status": status}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if status.get("error_msg"):
        return {"output_files": [str(result_file)], "summary": "",
                "error": f"AKO_writer 执行失败: {status['error_msg']}"}

    approval = status.get("human_approval_status", "")
    outline = status.get("outline") or {}
    if approval == "pending":
        summary = f"写作任务 {task_id}：选题/检索/大纲完成，待人工确认"
    elif outline:
        summary = f"写作任务 {task_id}：大纲产出完成"
    else:
        summary = f"写作任务 {task_id}：节点 {status.get('current_node', '?')}"
    return {"output_files": [str(result_file)], "summary": summary, "error": None}
