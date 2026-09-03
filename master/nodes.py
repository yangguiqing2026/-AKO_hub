"""
AKO Hub — Master Graph 节点实现
nodes.py: task_router, kb_allocator, workflow_caller, file_collector, error_handler

文档编号: AGE-TECH-AKO-HUB-001 §6.2

约束：
  - 本层只负责调度与元数据操作，不直接加载 LLM 或 Ollama 模型。
  - 所有 Spoke 调用通过 importlib 动态导入，失败时进入 error_handler。
  - 调用后扫描 output_dir 兜底，确保文件不遗漏。
"""

import os
import sys
import json
import subprocess
import importlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from master.state import MasterState
from registry.workflows import get_spoke_by_id, SpokeInfo
from core.ako_config.settings import get_config
from core.hub_db import HubDB
from core.knowledge_hub import KnowledgeHub
from core.file_bus import FileBus
from core.spoke_protocol import validate_spoke_output


# ── 辅助：从环境或配置推断路径（P1 简化版，P2 改为统一配置读取） ─────

def _resolve_hub_paths() -> Dict[str, str]:
    """从 ako_config 统一配置读取路径（P1 重构）。"""
    cfg = get_config()
    return {
        "sync_root": cfg.paths.sync_root,
        "db_path": cfg.paths.meta_db,
        "chroma_root": cfg.paths.chroma_root,
        "file_root": cfg.paths.file_root,
    }


# ── 内部辅助：分布式锁检查 ─────────────────────────────────────────

def _get_machine_id() -> str:
    """从 ako_config 读取 machine_id（P1 重构）。"""
    return get_config().machine_id


def _check_lock() -> tuple[bool, Optional[str]]:
    """检查分布式锁状态。返回 (是否可用, 持有者)。"""
    paths = _resolve_hub_paths()
    machine_id = _get_machine_id()
    from core.distributed_lock import DistributedLock
    lock = DistributedLock(paths["db_path"], machine_id)
    holder = lock.is_held()
    if holder is None or holder == machine_id:
        return True, holder
    return False, holder


# ── Node 1: task_router ───────────────────────────────────────────

def task_router(state: MasterState) -> Dict[str, Any]:
    """
    解析输入，确定 target_workflow。
    支持两种触发方式：
      1. 显式指定：payload 中含 "workflow_id"
      2. 关键词路由：payload 中含 "intent"，按意图匹配
    """
    # P3: 分布式锁预检查（执行类任务）
    try:
        lock_ok, holder = _check_lock()
        if not lock_ok:
            return {
                "status": "pending",
                "error_log": f"分布式锁被 {holder} 持有，本机 standby，请等待或手动释放",
                "started_at": datetime.now().isoformat(),
            }
    except Exception:
        pass  # 锁检查失败不阻断主流程

    payload = state.get("input_payload", {})
    workflow_id = payload.get("workflow_id")
    intent = payload.get("intent", "")

    # 1. 显式指定
    if workflow_id:
        spoke = get_spoke_by_id(workflow_id)
        if spoke is None:
            return {
                "status": "failed",
                "error_log": f"未注册的 workflow_id: {workflow_id}",
                "started_at": datetime.now().isoformat(),
            }
        if spoke.get("invoke_mode") == "manual_gui":
            # 批2 L0 注册级（GUI/工具型，2026-09-03）：看板可见但禁止 hub 调度
            return {
                "status": "failed",
                "error_log": f"{workflow_id} 为 L0 注册级（GUI/工具型），禁止 hub 调度，请通过其自身 GUI/流程使用",
                "started_at": datetime.now().isoformat(),
            }
        return {
            "target_workflow": workflow_id,
            "target_agent": spoke.get("entry_module"),
            "required_kb_ids": list(spoke.get("required_kb_ids", [])),
            "output_dir": spoke.get("output_dir", ""),
            "status": "pending",
        }

    # 优先级分组路由：数字越小优先级越高，P0 > P1 > P2 > P3，同优先级长度降序
    # 匹配顺序: P0(法律最高) > P1(核心业务) > P2(增值) > P3(通用)
    intent_routing: list[tuple[int, int, str, str]] = [
        # P0: 法律关键词（最高优先，数字小但后处理）
        (0, 4, "司法解释", "AKO_law_agent"),
        (0, 2, "法律",     "AKO_law_agent"),
        (0, 2, "立法",     "AKO_law_agent"),
        (0, 2, "法规",     "AKO_law_agent"),
        (0, 2, "合规",     "AKO_law_agent"),
        (0, 2, "仲裁",     "AKO_law_agent"),
        # P1: 核心业务关键词
        (1, 2, "结构",    "AKO_architect_agent"),
        (1, 2, "计算",    "AKO_architect_agent"),
        (1, 2, "设计",    "AKO_architect_agent"),
        (1, 2, "图纸",    "AKO_drawing_inspector"),
        (1, 2, "质检",    "AKO_drawing_inspector"),
        (1, 2, "图像",    "AKO_image_analyzer_agent"),
        (1, 2, "缺陷",    "AKO_image_analyzer_agent"),
        (1, 2, "识别",    "AKO_image_analyzer_agent"),
        # P2: 增值服务
        (2, 4, "报告生成", "AKO_reports"),
        (2, 3, "主流程",  "AKO工作流"),
        (2, 3, "全流程",  "AKO工作流"),
        (2, 3, "GEO",     "AKO_geo"),
        (2, 2, "商业",    "AKO_business_agent"),
        (2, 2, "报价",    "AKO_quote_agent"),
        (2, 2, "报表",    "AKO_reports"),
        (2, 2, "报告",    "AKO_reports"),
        (2, 2, "内容",    "AKO_geo"),
        (2, 2, "写作",    "AKO_writer_agent"),
        (2, 2, "文章",    "AKO_writer_agent"),
        (2, 2, "撰写",    "AKO_writer_agent"),
        (2, 2, "营销",    "AKO_geo"),
        (2, 2, "媒体",    "AKO_media_agent"),
        (2, 2, "编排",    "AKO工作流"),
        (2, 2, "问答",    "AKO_chat"),
        (2, 2, "规范",    "AKO_chat"),
        (2, 2, "查询",    "AKO_chat"),
        (2, 2, "知识",    "AKO_chat"),
        # P3: 通用兜底（数字最大，优先级最低）
        (3, 2, "审查",    "AKO_drawing_inspector"),
    ]

    matched = None
    # sorted 默认升序：key=(x[0], -x[1]) → P0(小)在前优先匹配，同优先级长度降序
    for _priority, _kw_len, keyword, wf in sorted(intent_routing, key=lambda x: (x[0], -x[1])):
        if keyword in intent:
            matched = wf
            break

    if matched:
        spoke = get_spoke_by_id(matched)
        if spoke is None:
            return {
                "status": "failed",
                "error_log": f"关键词 '{keyword}' 匹配到 {matched}，但该 workflow_id 未注册",
                "started_at": datetime.now().isoformat(),
            }
        return {
            "target_workflow": matched,
            "target_agent": spoke.get("entry_module"),
            "required_kb_ids": list(spoke.get("required_kb_ids", [])),
            "output_dir": spoke.get("output_dir", ""),
            "status": "pending",
        }

    return {
        "status": "failed",
        "error_log": f"无法解析意图: {intent}",
        "started_at": datetime.now().isoformat(),
    }


# ── Node 2: kb_allocator ──────────────────────────────────────────

def kb_allocator(state: MasterState) -> Dict[str, Any]:
    """
    校验 required_kb_ids 是否已注册。
    全部存在 → kb_status="ok"；任一缺失 → kb_status="missing"
    """
    paths = _resolve_hub_paths()
    kb_ids = state.get("required_kb_ids", [])
    if not kb_ids:
        return {"kb_status": "ok"}

    hub = KnowledgeHub(paths["db_path"], paths["chroma_root"])
    missing = []
    for kb_id in kb_ids:
        if not hub.is_kb_registered(kb_id):
            missing.append(kb_id)

    if missing:
        return {
            "kb_status": "missing",
            "error_log": f"缺失知识库: {', '.join(missing)}",
            "status": "failed",
        }
    return {"kb_status": "ok", "status": "running"}


# ── Node 3: workflow_caller ─────────────────────────────────────

def workflow_caller(state: MasterState) -> Dict[str, Any]:
    """
    调用 Spoke（Agent 或 Workflow）。
    P3 增强：执行前获取分布式锁，执行后释放。
    """
    # P3: 获取分布式锁
    paths = _resolve_hub_paths()
    machine_id = _get_machine_id()
    from core.distributed_lock import DistributedLock
    lock = DistributedLock(paths["db_path"], machine_id)
    if not lock.try_acquire(timeout_seconds=600):
        holder = lock.is_held()
        return {
            "status": "failed",
            "error_log": f"无法获取分布式锁，当前持有者: {holder}",
        }

    try:
        return _workflow_caller_core(state)
    finally:
        lock.release()


def _workflow_caller_core(state: MasterState) -> Dict[str, Any]:
    """
    原 workflow_caller 主体逻辑。
    """
    payload = state.get("input_payload", {})
    workflow_id = state.get("target_workflow", "")
    output_dir = state.get("output_dir", "")

    spoke = get_spoke_by_id(workflow_id)
    if spoke is None:
        return {
            "status": "failed",
            "error_log": f"workflow_caller 未找到注册信息: {workflow_id}",
        }

    # 构建输出目录绝对路径
    paths = _resolve_hub_paths()
    abs_output_dir = Path(paths["file_root"]) / output_dir if output_dir else Path(paths["file_root"])
    abs_output_dir.mkdir(parents=True, exist_ok=True)

    # 将输出目录写入 payload，供 Spoke 使用
    enriched_payload = dict(payload)
    enriched_payload["_hub_output_dir"] = str(abs_output_dir)
    enriched_payload["_hub_db_path"] = paths["db_path"]
    enriched_payload["_hub_chroma_root"] = paths["chroma_root"]
    enriched_payload["_hub_file_root"] = paths["file_root"]

    # 记录调用前文件快照（用于比对新增文件）
    pre_files = set()
    if abs_output_dir.exists():
        pre_files = {str(p) for p in abs_output_dir.rglob("*") if p.is_file()}

    spoke_output = {"output_files": [], "summary": "", "error": None}

    try:
        invoke_mode = spoke.get("invoke_mode", "importlib")

        if invoke_mode == "subprocess":
            spoke_output = _call_spoke_subprocess(spoke, enriched_payload, abs_output_dir)
        else:
            entry_mod = spoke.get("entry_module", "")
            entry_func = spoke.get("entry_function")

            if not entry_mod:
                raise ValueError("entry_module 为空")

            # P4: 若 Spoke 配置了 source_dir，将其加入 sys.path 以便动态导入
            source_dir = spoke.get("source_dir", "")
            path_inserted = False
            src = ""
            if source_dir and Path(source_dir).exists():
                src = str(Path(source_dir).resolve())
                if src not in sys.path:
                    sys.path.insert(0, src)
                    path_inserted = True

            try:
                try:
                    # 动态导入（source_dir 已加入 sys.path，外部项目自带 agents 包时优先）
                    mod = importlib.import_module(entry_mod)
                except ModuleNotFoundError:
                    # 回退：内置适配器（quote/architect 等）位于 hub 的 agents/ 包，
                    # 其外部目录没有同名模块——退掉 source_dir 后从 hub 包导入
                    if path_inserted and src in sys.path:
                        sys.path.remove(src)
                        path_inserted = False
                    mod = importlib.import_module(entry_mod)
            finally:
                # 清理临时加入的路径，避免污染全局
                if path_inserted and src in sys.path:
                    sys.path.remove(src)

            if spoke.get("spoke_type") == "workflow" and entry_func is None:
                # LangGraph 子图：假设模块中暴露 compiled graph 对象
                graph = getattr(mod, "graph", None) or getattr(mod, "compiled_graph", None)
                if graph is None:
                    raise ValueError(f"模块 {entry_mod} 中未找到 graph 或 compiled_graph")
                result = graph.invoke(enriched_payload)
                spoke_output = _normalize_workflow_result(result)
            else:
                # Agent：调用入口函数
                func = getattr(mod, entry_func, None) if entry_func else None
                if func is None:
                    raise ValueError(f"模块 {entry_mod} 中未找到入口函数 {entry_func}")
                result = func(**enriched_payload)
                spoke_output = _normalize_agent_result(result)

    except Exception as e:
        spoke_output["error"] = f"{type(e).__name__}: {e}"
        return {
            "status": "failed",
            "error_log": spoke_output["error"],
            "spoke_output": spoke_output,
        }

    # Spoke 输出协议校验
    valid, validation_err = validate_spoke_output(spoke_output)
    if not valid:
        print(f"[WARN] Spoke {workflow_id} 输出不合规: {validation_err}")
        # 不阻断流程，但在 error_log 中记录警告

    # 扫描 output_dir，发现新增文件
    post_files = set()
    if abs_output_dir.exists():
        post_files = {str(p) for p in abs_output_dir.rglob("*") if p.is_file()}

    new_files = list(post_files - pre_files)
    # 合并 Spoke 返回的文件与扫描发现的文件
    all_files = list(set(spoke_output.get("output_files", []) + new_files))

    result: Dict[str, Any] = {
        "spoke_output": spoke_output,
        "spoke_output_paths": all_files,
        "status": "running" if not spoke_output.get("error") else "failed",
    }
    if spoke_output.get("error"):
        # 将 Spoke 返回的错误透传到 error_log，避免被 error_handler 丢弃成 None
        result["error_log"] = spoke_output["error"]
    return result


def _call_spoke_subprocess(
    spoke: SpokeInfo,
    payload: Dict[str, Any],
    output_dir: Path,
) -> Dict[str, Any]:
    """
    subprocess 模式调用 Spoke。
    将 payload 序列化为 JSON，通过 stdin 传给适配器脚本，
    从 stdout 读取 JSON 结果，并检查 _DONE.json 完成信号。
    """
    source_dir = spoke.get("source_dir", "")
    entry_mod = spoke.get("entry_module", "")
    entry_func = spoke.get("entry_function", "run")

    # 构建适配器脚本路径
    if source_dir and entry_mod:
        # entry_module 如 "agents.ako_reports_adapter" → "agents/ako_reports_adapter.py"
        script_rel = entry_mod.replace(".", "/") + ".py"
        script_path = Path(source_dir) / script_rel
        if script_path.exists():
            adapter_script = str(script_path)
        else:
            # 回退：在 Hub 的 agents 目录下查找
            hub_root = Path(__file__).resolve().parent.parent
            fallback = hub_root / script_rel
            adapter_script = str(fallback) if fallback.exists() else None
    else:
        adapter_script = None

    if not adapter_script or not Path(adapter_script).exists():
        return {
            "output_files": [],
            "summary": "",
            "error": f"subprocess 适配器脚本不存在: {adapter_script or 'N/A'}",
        }

    # 序列化 payload
    payload_json = json.dumps(payload, ensure_ascii=False)

    try:
        result = subprocess.run(
            [sys.executable, adapter_script],
            input=payload_json,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            cwd=str(Path(adapter_script).parent),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        if result.returncode != 0:
            return {
                "output_files": [],
                "summary": "",
                "error": f"subprocess 退出码 {result.returncode}: {result.stderr[:500]}",
            }

        # 解析 stdout JSON
        try:
            spoke_output = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError:
            spoke_output = {
                "output_files": [],
                "summary": result.stdout[:500] if result.stdout else "",
                "error": None,
            }

        # 检查 _DONE.json
        done_file = output_dir / "_DONE.json"
        if done_file.exists():
            done_data = json.loads(done_file.read_text(encoding="utf-8"))
            spoke_output["output_files"] = list(set(
                spoke_output.get("output_files", []) + done_data.get("output_files", [])
            ))
            if not spoke_output.get("summary") and done_data.get("summary"):
                spoke_output["summary"] = done_data["summary"]
            if not spoke_output.get("error") and done_data.get("error"):
                spoke_output["error"] = done_data["error"]

        return spoke_output

    except subprocess.TimeoutExpired:
        return {"output_files": [], "summary": "", "error": "subprocess 调用超时（600 秒）"}
    except Exception as e:
        return {"output_files": [], "summary": "", "error": f"subprocess 调用失败: {type(e).__name__}: {e}"}


def _normalize_agent_result(result: Any) -> Dict[str, Any]:
    """将 Agent 各种返回格式归一化为 SpokeOutput。"""
    if result is None:
        return {"output_files": [], "summary": "", "error": None}
    if isinstance(result, dict):
        return {
            "output_files": result.get("output_files", []) if isinstance(result.get("output_files"), list) else [],
            "summary": result.get("summary", ""),
            "error": result.get("error"),
        }
    if isinstance(result, str):
        return {"output_files": [], "summary": result, "error": None}
    if isinstance(result, (list, tuple)):
        return {"output_files": list(result), "summary": "", "error": None}
    return {"output_files": [], "summary": str(result), "error": None}


def _normalize_workflow_result(result: Any) -> Dict[str, Any]:
    """将 Workflow 返回格式归一化。"""
    if result is None:
        return {"output_files": [], "summary": "", "error": None}
    if isinstance(result, dict):
        # LangGraph 最终状态通常是一个 dict，从中提取 output_files
        files = result.get("output_files", [])
        if not isinstance(files, list):
            files = []
        # 有些节点会把文件路径放在 state 中其他字段
        if not files:
            for key in ["generated_files", "file_paths", "output_path"]:
                val = result.get(key)
                if isinstance(val, list):
                    files.extend(val)
                elif isinstance(val, str):
                    files.append(val)
        return {
            "output_files": files,
            "summary": result.get("summary", ""),
            "error": result.get("error"),
        }
    return _normalize_agent_result(result)


# ── Node 4: file_collector ────────────────────────────────────────

def file_collector(state: MasterState) -> Dict[str, Any]:
    """
    将 Spoke 产出的文件批量注册到 file_registry。
    如果 Spoke 未返回文件路径，则扫描 output_dir 兜底。
    """
    paths = _resolve_hub_paths()
    bus = FileBus(paths["db_path"], paths["file_root"])
    hub = KnowledgeHub(paths["db_path"], paths["chroma_root"])

    spoke_paths = state.get("spoke_output_paths", [])
    output_dir = state.get("output_dir", "")
    workflow_id = state.get("target_workflow", "")
    spoke = get_spoke_by_id(workflow_id)
    source_agent = spoke.get("name", workflow_id) if spoke else workflow_id

    # 兜底扫描
    if not spoke_paths and output_dir:
        scan_dir = Path(paths["file_root"]) / output_dir
        if scan_dir.exists():
            spoke_paths = [str(p) for p in scan_dir.rglob("*") if p.is_file()]

    file_root_path = Path(paths["file_root"]).resolve()
    registered_ids: List[str] = []

    for abs_path in spoke_paths:
        p = Path(abs_path).resolve()
        if not p.exists():
            continue
        try:
            rel_path = str(p.relative_to(file_root_path))
        except ValueError:
            # 文件不在 file_root 下，跳过注册（或复制进去？先跳过）
            continue

        file_type = p.suffix.lower().lstrip(".")
        project_tag = _infer_project_tag(rel_path)

        try:
            fid = bus.register(
                source_agent=source_agent,
                source_node=state.get("target_workflow", ""),
                rel_path=rel_path,
                file_type=file_type,
                project_tag=project_tag,
                version_tag="v0.1",  # P1 简化，后续从 payload 读取
            )
            registered_ids.append(fid)
        except Exception as e:
            # 单条失败不影响其他
            print(f"[WARN] file_collector 注册失败 {abs_path}: {e}")

    return {
        "generated_files": registered_ids,
        "status": "running" if registered_ids else "done",
    }


def _infer_project_tag(rel_path: str) -> str:
    """根据路径推断项目标签。"""
    if "taoli" in rel_path.lower():
        return "taoli"
    if "sample" in rel_path.lower():
        return "sample"
    return "common"


# ── Node 5: error_handler ─────────────────────────────────────────

def error_handler(state: MasterState) -> Dict[str, Any]:
    """
    统一错误处理：
      1. 若 retry_count < max_retry，标记为 pending 等待重试。
      2. 否则将错误信息写入 task_queue，标记为 failed。
    """
    paths = _resolve_hub_paths()
    task_id = state.get("task_id", "")
    error_log = state.get("error_log", "")
    retry_count = state.get("retry_count", 0)
    max_retry = state.get("max_retry", 3)

    # 可重试：递增计数，重置状态，让图回到 workflow_caller
    if retry_count < max_retry:
        new_count = retry_count + 1
        print(f"[RETRY] 任务 {task_id} 第 {new_count}/{max_retry} 次重试: {error_log}")
        return {
            "retry_count": new_count,
            "status": "running",  # 非 failed，条件路由将导向 workflow_caller
            "error_log": f"重试 {new_count}/{max_retry}: {error_log}",
        }

    # 不可重试：写入最终失败记录
    try:
        with HubDB(paths["db_path"]) as db:
            db.execute(
                """INSERT INTO task_queue
                   (task_id, workflow_id, trigger_agent, status, error_log, finished_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       status=excluded.status,
                       error_log=excluded.error_log,
                       finished_at=excluded.finished_at""",
                (task_id, state.get("target_workflow", ""), state.get("trigger_agent", "manual"),
                 "failed", error_log, datetime.now().isoformat()),
            )
    except Exception:
        pass  # task_queue 写入失败不阻断主流程

    return {
        "status": "failed",
        "finished_at": datetime.now().isoformat(),
    }


# ── Node 7: sync_monitor ────────────────────────────────────────

def sync_monitor(state: MasterState) -> Dict[str, Any]:
    """
    文件同步状态监控节点。

    职责：
      1. 扫描 file_registry 中指定范围（project_tag 或全部）的文件。
      2. 计算本地文件 SHA-256，与注册表比对。
      3. 更新 file_registry.is_synced 与 sync_verified_at。
      4. 写入 sync_log 表。

    使用方式：
      - 作为 Master Graph 的扩展节点（在 state_aggregator 后调用）。
      - 独立 CLI 调用：python master/runner.py --sync-check taoli
    """
    paths = _resolve_hub_paths()
    bus = FileBus(paths["db_path"], paths["file_root"])

    project_tag = state.get("input_payload", {}).get("project_tag", "")
    task_id = state.get("task_id", "")

    machine_id = get_config().machine_id

    # 获取待校验文件列表
    if project_tag:
        files = bus.find_by_project(project_tag)
    else:
        # 获取全部未校验或最近校验的文件（简化：取最近 100 条）
        with HubDB(paths["db_path"]) as db:
            files = db.fetchall(
                "SELECT * FROM file_registry ORDER BY created_at DESC LIMIT 100"
            )

    results = {"match": 0, "mismatch": 0, "missing": 0, "details": []}

    for row in files:
        file_id = row["file_id"]
        abs_path = row["abs_path"]
        registered_hash = row.get("file_hash", "")

        # 文件缺失
        if not Path(abs_path).exists():
            results["missing"] += 1
            _write_sync_log(paths["db_path"], file_id, machine_id, "", registered_hash, "missing")
            with HubDB(paths["db_path"]) as db:
                db.execute(
                    "UPDATE file_registry SET is_synced=2, sync_verified_at=? WHERE file_id=?",
                    (datetime.now().isoformat(), file_id),
                )
            results["details"].append({"file_id": file_id, "status": "missing"})
            continue

        # 计算当前哈希
        try:
            current_hash = bus.compute_hash(abs_path)
        except Exception as e:
            results["missing"] += 1
            results["details"].append({"file_id": file_id, "status": f"hash_error: {e}"})
            continue

        # 比对
        if registered_hash and current_hash == registered_hash:
            results["match"] += 1
            status = "match"
            is_synced = 1
        else:
            results["mismatch"] += 1
            status = "mismatch"
            is_synced = 2

        _write_sync_log(paths["db_path"], file_id, machine_id, current_hash, registered_hash, status)
        with HubDB(paths["db_path"]) as db:
            db.execute(
                "UPDATE file_registry SET is_synced=?, sync_verified_at=? WHERE file_id=?",
                (is_synced, datetime.now().isoformat(), file_id),
            )
        results["details"].append({
            "file_id": file_id,
            "status": status,
            "registered_hash": registered_hash[:16] + "..." if registered_hash else "",
            "current_hash": current_hash[:16] + "...",
        })

    total = len(files)
    summary = (
        f"同步校验完成: 总计 {total} 个文件, "
        f"一致 {results['match']}, 冲突 {results['mismatch']}, 缺失 {results['missing']}"
    )

    return {
        "sync_status": "ok" if results["mismatch"] == 0 and results["missing"] == 0 else "partial",
        "sync_summary": summary,
        "sync_results": results,
    }


def _write_sync_log(db_path: str, file_id: str, machine_id: str,
                    local_hash: str, peer_hash: str, status: str) -> None:
    """写入 sync_log 表。"""
    try:
        with HubDB(db_path) as db:
            db.execute(
                """INSERT INTO sync_log
                   (file_id, machine_id, local_hash, peer_hash, status, checked_at)
                   VALUES (?,?,?,?,?,?)""",
                (file_id, machine_id, local_hash, peer_hash, status, datetime.now().isoformat()),
            )
    except Exception:
        pass  # sync_log 写入失败不阻断


# ── 独立工具函数（供 CLI 直接调用） ─────────────────────────────────

def standalone_sync_check(project_tag: str = "", db_path: str = "", file_root: str = "") -> Dict[str, Any]:
    """
    独立同步校验，不依赖 Master Graph 状态。
    CLI 直接调用此函数。
    """
    if not db_path or not file_root:
        paths = _resolve_hub_paths()
        db_path = paths["db_path"]
        file_root = paths["file_root"]

    bus = FileBus(db_path, file_root)
    machine_id = get_config().machine_id

    if project_tag:
        files = bus.find_by_project(project_tag)
    else:
        with HubDB(db_path) as db:
            files = db.fetchall(
                "SELECT * FROM file_registry ORDER BY created_at DESC LIMIT 100"
            )

    results = {"match": 0, "mismatch": 0, "missing": 0, "details": []}

    for row in files:
        file_id = row["file_id"]
        abs_path = row["abs_path"]
        registered_hash = row.get("file_hash", "")

        if not Path(abs_path).exists():
            results["missing"] += 1
            _write_sync_log(db_path, file_id, machine_id, "", registered_hash, "missing")
            with HubDB(db_path) as db:
                db.execute(
                    "UPDATE file_registry SET is_synced=2, sync_verified_at=? WHERE file_id=?",
                    (datetime.now().isoformat(), file_id),
                )
            results["details"].append({"file_id": file_id, "status": "missing"})
            continue

        try:
            current_hash = bus.compute_hash(abs_path)
        except Exception as e:
            results["missing"] += 1
            results["details"].append({"file_id": file_id, "status": f"hash_error: {e}"})
            continue

        if registered_hash and current_hash == registered_hash:
            results["match"] += 1
            status = "match"
            is_synced = 1
        else:
            results["mismatch"] += 1
            status = "mismatch"
            is_synced = 2

        _write_sync_log(db_path, file_id, machine_id, current_hash, registered_hash, status)
        with HubDB(db_path) as db:
            db.execute(
                "UPDATE file_registry SET is_synced=?, sync_verified_at=? WHERE file_id=?",
                (is_synced, datetime.now().isoformat(), file_id),
            )
        results["details"].append({
            "file_id": file_id, "status": status,
            "registered_hash": registered_hash[:16] + "..." if registered_hash else "",
            "current_hash": current_hash[:16] + "...",
        })

    total = len(files)
    summary = (
        f"同步校验: 总计 {total} 个文件, "
        f"一致 {results['match']}, 冲突 {results['mismatch']}, 缺失 {results['missing']}"
    )
    return {"sync_summary": summary, "sync_results": results}


# ── Node 6: state_aggregator ──────────────────────────────────────

def state_aggregator(state: MasterState) -> Dict[str, Any]:
    """
    最终节点：
      1. 将 task 完成状态写入 task_queue。
      2. 生成 output_summary。
    """
    paths = _resolve_hub_paths()
    task_id = state.get("task_id", "")
    generated_files = state.get("generated_files", [])
    spoke_output = state.get("spoke_output", {})

    summary = spoke_output.get("summary", "") if isinstance(spoke_output, dict) else ""
    if not summary and generated_files:
        summary = f"完成，注册 {len(generated_files)} 个文件"

    try:
        with HubDB(paths["db_path"]) as db:
            output_ids = json.dumps(generated_files) if generated_files else ""
            db.execute(
                """INSERT INTO task_queue
                   (task_id, workflow_id, trigger_agent, status,
                    output_file_ids, error_log, finished_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       status=excluded.status,
                       output_file_ids=excluded.output_file_ids,
                       error_log=excluded.error_log,
                       finished_at=excluded.finished_at""",
                (task_id, state.get("target_workflow", ""), state.get("trigger_agent", "manual"),
                 "done", output_ids, summary, datetime.now().isoformat()),
            )
    except Exception:
        pass

    return {
        "status": "done",
        "output_summary": summary,
        "finished_at": datetime.now().isoformat(),
    }
