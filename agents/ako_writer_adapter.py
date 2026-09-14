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
from typing import Any, Dict, List

SOURCE_DIR = Path(r"D:\AKO\AKO_writer_agent")
SHARED_DIR = Path(r"D:\AKO\AKO_shared")  # 统一命名模块（architect/writer 共享）
POLL_INTERVAL = 2.0
# 自动放行全链（2026-09-09）：N1 检索 / N3 长文写作 / N5 排版多次 LLM 调用，
# 240s 不足以跑完全程 → 放宽至 20 分钟。
POLL_TIMEOUT = 1200.0
# 确认关卡总数上限：writer 图含 N0/N2/N4 三道人工确认关（恒自动放行），
# 6 次上限兼作死循环护栏。
MAX_AUTO_CONFIRM = 6


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

    # 驱动至终态（2026-09-09 修复：此前挂在 N0 人工确认关即当成功返回，
    # 任务恒 done 但永无 Word 产物）。writer 图含 N0/N2/N4 三道人工确认关，
    # 设计预期由外部代码确认后重新 invoke；hub 调度链无人接线 → 此处自动
    # 放行：能走到 writer 的工单已通过治理授权（老板批准放行或大门投递），
    # 确认关不再二次要人。每次放行注入 approved 并重跑状态机推进到下一关
    # 或 N5（Word 排版）终态。
    status: Dict[str, Any] = {}
    start = time.time()
    auto_confirms = 0
    while time.time() - start < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            status = _run_async(spoke.get_task_status(task_id)) or {}
        except Exception:
            continue
        if status.get("error_msg"):
            break
        if status.get("human_approval_status") == "pending":
            if auto_confirms >= MAX_AUTO_CONFIRM:
                status = {**status, "error_msg": "writer 确认环超过上限仍未收敛，中止"}
                break
            auto_confirms += 1
            try:
                _run_async(spoke.submit_human_confirm(task_id, approved=True))
                continue  # 放行后继续轮询（invoke 内已推进，下次读取新状态）
            except Exception as exc:  # noqa: BLE001
                status = {**status, "error_msg": f"writer 自动放行失败: {exc}"}
                break
        else:
            # approved/rejected 终态（图已跑完到 END / N5 产出）
            break
    else:
        status = {**status, "error_msg": f"writer 驱动轮询超时（{POLL_TIMEOUT:.0f}s）"}
        status.setdefault("current_node", "unknown")

    # 结果落盘：状态回执 json（适配器自身产出，始终写进 hub 输出目录）
    result_file = output_dir / f"writer_task_{task_id}.json"
    result_file.write_text(
        json.dumps({"task_id": task_id, "status": status}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_files: List[str] = [str(result_file)]

    # 2026-09-14：writer 的 OUTPUT_ROOT 已直接指向 hub 的 file_bus/writer_output
    # （工作台下载区），产物一步到位 —— 此处不再 shutil 拷第二份，直接登记原位路径。
    docx_path = (status.get("formatted_docx") or {}).get("path")
    if docx_path and Path(docx_path).exists():
        output_files.insert(0, str(docx_path))  # Word 产物列首位

    if status.get("error_msg"):
        return {"output_files": output_files, "summary": "",
                "error": f"AKO_writer 执行失败: {status['error_msg']}"}

    if docx_path and Path(docx_path).exists():
        summary = f"写作任务 {task_id}：已完成并输出 Word 文档 {Path(docx_path).name}"
    else:
        summary = f"写作任务 {task_id}：完成（节点 {status.get('current_node', '?')}，未产出 Word）"
    return {"output_files": output_files, "summary": summary, "error": None}
