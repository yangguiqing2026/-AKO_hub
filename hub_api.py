"""
AKO Hub — 外部 API 接口
hub_api.py: 提供 JSON 可序列化的函数接口，供 cherry_studio / kimi_desktop / 第三方脚本调用。

调用方式：
    import sys
    sys.path.insert(0, "D:/BaiduSyncdisk/AKO_Hub")
    from hub_api import submit_task, sync_check, hub_status, list_files

    result = submit_task({"intent": "结构计算", "project_tag": "taoli"})
    print(result["status"])

文档编号: AGE-TECH-AKO-HUB-001 §P2
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from master.state import MasterState
from master.nodes import standalone_sync_check
from core.hub_db import HubDB
from core.file_bus import FileBus
from core.knowledge_hub import KnowledgeHub
from registry.workflows import (
    SpokeInfo, list_all_spokes, get_spoke_by_id,
    register_spoke, unregister_spoke, get_spokes_by_source_dir,
    enrich_spoke, list_spokes_enriched, list_unclassified,
)
from registry.taxonomy import (
    VALID_DOMAINS, VALID_FUNCTIONS,
    get_domain, get_function, get_category,
    list_by_domain, list_by_function,
    find_unclassified,
)


# ── 内部：路径解析 ───────────────────────────────────────────────

def _resolve_paths() -> Dict[str, str]:
    """读取 config/hub.yaml 返回路径字典。"""
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent / "config" / "hub.yaml"
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
        default_root = Path(__file__).resolve().parent
        return {
            "sync_root": str(default_root),
            "db_path": str(default_root / "age_hub.db"),
            "chroma_root": str(default_root / "chroma_db"),
            "file_root": str(default_root / "files"),
        }


# ── API 1: submit_task ───────────────────────────────────────────

def call_llm(prompt: str, model: str = "openai/qwen3-14b",
             fallback_chain: Optional[List[str]] = None) -> Dict[str, str]:
    """调用本地 OpenAI 兼容 LLM 端点（WSL llama.cpp :8081）。

    端点/密钥可用环境变量 OPENAI_API_BASE / OPENAI_API_KEY 覆盖，
    默认模型 openai/qwen3-14b、默认密钥 sk-ako-local（内网本地服务）。
    支持 fallback_chain 依次重试；全部失败抛 RuntimeError，
    调用方（ako_geo n3/n5）既有 except 会沿占位降级路径处理。

    返回: {"content": "<模型输出文本>"}
    """
    import os

    base = os.environ.get("OPENAI_API_BASE", "http://localhost:8081/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "sk-ako-local")
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("hub_api.call_llm 需要 requests 依赖") from e

    models = [model] + [m for m in (fallback_chain or []) if m]
    last_err: Optional[Exception] = None
    for m in models:
        try:
            resp = requests.post(
                f"{base.rstrip('/')}/chat/completions",
                json={"model": m, "messages": [{"role": "user", "content": prompt}]},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return {"content": content}
        except Exception as e:
            last_err = e
    raise RuntimeError(f"call_llm 全部模型调用失败: {last_err}")


def submit_task(payload: Dict[str, Any], task_id: Optional[str] = None,
                trigger: str = "external") -> Dict[str, Any]:
    """
    提交任务到 Master Graph 执行。

    Args:
        payload: 任务参数字典，可包含 intent / workflow_id / project_tag 等
        task_id: 可选任务 ID，默认自动生成
        trigger: 触发源，如 "cherry_studio" / "kimi_desktop" / "manual"

    Returns:
        最终 MasterState 字典
    """
    # 延迟导入：避免 hub_api 被 import 时强制加载 langgraph
    from master.graph import get_master_graph

    paths = _resolve_paths()
    graph = get_master_graph()
    task_id = task_id or f"T-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

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
        return dict(result)
    except Exception as e:
        return {
            "task_id": task_id,
            "status": "failed",
            "error_log": f"{type(e).__name__}: {e}",
            "finished_at": datetime.now().isoformat(),
        }


# ── API 2: sync_check ────────────────────────────────────────────

def sync_check(project_tag: str = "", verbose: bool = False) -> Dict[str, Any]:
    """
    执行文件同步一致性校验。

    Args:
        project_tag: 项目标签，空字符串则校验最近 100 个文件
        verbose: 是否返回详细列表

    Returns:
        {"sync_summary": str, "sync_results": dict}
    """
    result = standalone_sync_check(project_tag=project_tag)
    if not verbose:
        # 精简输出，不返回逐条详情
        result["sync_results"]["details"] = []
    return result


# ── API 3: hub_status ────────────────────────────────────────────

def hub_status() -> Dict[str, Any]:
    """
    查询 AKO Hub 全局状态统计。

    Returns:
        {"tasks": [...], "files": [...], "knowledge_bases": int}
    """
    paths = _resolve_paths()
    with HubDB(paths["db_path"]) as db:
        tasks = db.fetchall("SELECT status, COUNT(*) as cnt FROM task_queue GROUP BY status")
        files = db.fetchall("SELECT is_synced, COUNT(*) as cnt FROM file_registry GROUP BY is_synced")
        kbs = db.fetchall("SELECT COUNT(*) as cnt FROM knowledge_base")

    return {
        "tasks": [{"status": t["status"], "count": t["cnt"]} for t in tasks],
        "files": [
            {"status": {0: "unchecked", 1: "synced", 2: "conflict"}.get(f["is_synced"], "unknown"),
             "count": f["cnt"]}
            for f in files
        ],
        "knowledge_bases": kbs[0]["cnt"] if kbs else 0,
    }


# ── API 4: list_files ────────────────────────────────────────────

def list_files(project_tag: str = "", agent_name: str = "",
               file_type: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """
    列出注册的文件。

    Args:
        project_tag: 项目过滤
        agent_name: Agent 过滤
        file_type: 文件类型过滤
        limit: 最大返回数量

    Returns:
        文件字典列表
    """
    paths = _resolve_paths()
    bus = FileBus(paths["db_path"], paths["file_root"])

    if project_tag:
        rows = bus.find_by_project(project_tag, file_type)
    elif agent_name:
        rows = bus.find_by_agent(agent_name, project_tag)
    else:
        with HubDB(paths["db_path"]) as db:
            rows = db.fetchall(
                "SELECT * FROM file_registry ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

    return rows[:limit]


# ── API 5: list_knowledge_bases ───────────────────────────────────

def list_knowledge_bases(agent_name: str = "", project_tag: str = "") -> List[Dict[str, Any]]:
    """
    列出知识库。

    Args:
        agent_name: 按 Agent 过滤
        project_tag: 按项目过滤

    Returns:
        知识库字典列表
    """
    paths = _resolve_paths()
    kh = KnowledgeHub(paths["db_path"], paths["chroma_root"])

    if agent_name:
        return kh.list_kb_by_agent(agent_name)
    elif project_tag:
        return kh.list_kb_by_project(project_tag)
    return kh.list_all_kb()


# ── API 6: get_task_detail ───────────────────────────────────────

def get_task_detail(task_id: str) -> Optional[Dict[str, Any]]:
    """查询单个任务详情。"""
    paths = _resolve_paths()
    with HubDB(paths["db_path"]) as db:
        row = db.fetchone("SELECT * FROM task_queue WHERE task_id=?", (task_id,))
    return row


# ── API 7: lock_status ───────────────────────────────────────────

def lock_status() -> Dict[str, Any]:
    """
    查询分布式锁状态。

    Returns:
        {"holder": str|None, "held_by_self": bool, "machine_id": str}
    """
    paths = _resolve_paths()
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        machine_id = cfg.get("machine_id", "machine_01")
    except Exception:
        machine_id = "machine_01"

    from core.distributed_lock import DistributedLock
    lock = DistributedLock(paths["db_path"], machine_id)
    holder = lock.is_held()
    return {
        "holder": holder,
        "held_by_self": holder == machine_id,
        "machine_id": machine_id,
        "db_path": paths["db_path"],
    }


# ── API 8: acquire_lock / release_lock ───────────────────────────

def acquire_lock(timeout_seconds: int = 300) -> Dict[str, Any]:
    """手动获取锁。供外部脚本或管理操作使用。"""
    paths = _resolve_paths()
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        machine_id = cfg.get("machine_id", "machine_01")
    except Exception:
        machine_id = "machine_01"

    from core.distributed_lock import DistributedLock
    lock = DistributedLock(paths["db_path"], machine_id)
    ok = lock.try_acquire(timeout_seconds=timeout_seconds)
    return {
        "acquired": ok,
        "holder": lock.is_held(),
        "machine_id": machine_id,
    }


def release_lock() -> Dict[str, Any]:
    """手动释放锁。"""
    paths = _resolve_paths()
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent / "config" / "hub.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        machine_id = cfg.get("machine_id", "machine_01")
    except Exception:
        machine_id = "machine_01"

    from core.distributed_lock import DistributedLock
    lock = DistributedLock(paths["db_path"], machine_id)
    ok = lock.release()
    return {
        "released": ok,
        "holder": lock.is_held(),
        "machine_id": machine_id,
    }


# ── API 9: register_spoke_api ────────────────────────────────

def register_spoke_api(
    workflow_id: str,
    name: str,
    spoke_type: str,
    entry_module: str,
    source_dir: str,
    entry_function: str = "run",
    required_kb_ids: Optional[List[str]] = None,
    output_dir: str = "",
    description: str = "",
    invoke_mode: str = "importlib",
    domain: str = "",
    function: str = "",
) -> Dict[str, Any]:
    """
    注册一个新的 Spoke（Agent 或 Workflow）到 AKO Hub。

    Args:
        workflow_id: 唯一标识，如 "wf_ako_architect"
        name: 显示名称
        spoke_type: "agent" | "workflow" | "subgraph"
        entry_module: Python 模块入口（相对于 source_dir）
        source_dir: Spoke 项目源码所在绝对路径
        entry_function: 入口函数名，workflow 类型可留空
        required_kb_ids: 所需知识库 ID 列表
        output_dir: 输出目录（相对于 files/）
        description: 描述信息
        invoke_mode: "importlib" (默认) | "subprocess"
        domain: 业务域（可选，来自 registry/taxonomy.py 枚举）
        function: 功能类型（可选，来自 registry/taxonomy.py 枚举）

    Returns:
        {"registered": bool, "workflow_id": str, "message": str}
    """
    spoke_info: SpokeInfo = {
        "workflow_id": workflow_id,
        "name": name,
        "spoke_type": spoke_type,
        "entry_module": entry_module,
        "entry_function": entry_function if entry_function else None,
        "required_kb_ids": required_kb_ids or [],
        "output_dir": output_dir,
        "description": description,
        "status": "registered",
        "source_dir": source_dir.replace("\\", "/"),
        "invoke_mode": invoke_mode,
    }
    is_new = register_spoke(spoke_info)
    classification_saved = True
    if domain and function:
        from registry.taxonomy import set_classification
        classification_saved = set_classification(workflow_id, domain, function)
    return {
        "registered": True,
        "workflow_id": workflow_id,
        "is_new": is_new,
        "domain": domain,
        "function": function,
        "classification_saved": classification_saved,
        "message": f"新增注册: {workflow_id}" if is_new else f"更新已有: {workflow_id}",
    }


# ── API 10: list_spokes ───────────────────────────────────

def list_spokes(spoke_type: str = "") -> List[Dict[str, Any]]:
    """
    列出已注册的 Spoke（Agent/Workflow）。

    Args:
        spoke_type: 过滤类型，空则返回全部

    Returns:
        Spoke 信息字典列表
    """
    spokes = list_all_spokes()
    if spoke_type:
        spokes = [s for s in spokes if s["spoke_type"] == spoke_type]
    return [dict(s) for s in spokes]


# ── API 11: remove_spoke ──────────────────────────────────

def remove_spoke(workflow_id: str) -> Dict[str, Any]:
    """移除一个已注册的 Spoke。"""
    ok = unregister_spoke(workflow_id)
    return {
        "removed": ok,
        "workflow_id": workflow_id,
        "message": f"已移除: {workflow_id}" if ok else f"未找到: {workflow_id}",
    }


# ── API 12: taxonomy（Agent 分类学） ──────────────────────────

def taxonomy_list() -> Dict[str, Any]:
    """
    查询完整分类学：三维枚举 + 全部 Agent 的分类映射 + 未分类清单。

    Returns:
        {
            "domains": [...],
            "functions": [...],
            "mapping": {workflow_id: {"domain": str, "function": str}},
            "unclassified": [...],
        }
    """
    mapping = {}
    for spoke in list_spokes_enriched():
        mapping[spoke["workflow_id"]] = {
            "domain": spoke.get("domain", ""),
            "function": spoke.get("function", ""),
            "category": spoke.get("category", ""),
        }

    return {
        "domains": sorted(VALID_DOMAINS),
        "functions": sorted(VALID_FUNCTIONS),
        "mapping": mapping,
        "unclassified": list_unclassified(),
    }


def classify_agent(workflow_id: str) -> Dict[str, Any]:
    """
    查询单个 Agent 的三维分类。

    Args:
        workflow_id: Agent workflow_id

    Returns:
        {"workflow_id": str, "domain": str, "function": str, "category": str}
        未分类时 domain/function 为空字符串。
    """
    return {
        "workflow_id": workflow_id,
        "domain": get_domain(workflow_id),
        "function": get_function(workflow_id),
        "category": get_category(workflow_id),
    }


def list_agents_by_domain(domain: str) -> List[str]:
    """按业务域列出全部 Agent workflow_id。"""
    return list_by_domain(domain)


def list_agents_by_function(function: str) -> List[str]:
    """按功能类型列出全部 Agent workflow_id。"""
    return list_by_function(function)


def unclassified_agents() -> List[str]:
    """列出「未分类」的 Agent workflow_id。"""
    return list_unclassified()


# ── 便捷：直接运行的 CLI 兼容（保留向后兼容） ─────────────────────

if __name__ == "__main__":
    # 简单测试：打印 hub_status
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(hub_status(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "sync":
        project = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(sync_check(project), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "lock":
        print(json.dumps(lock_status(), ensure_ascii=False, indent=2))
    else:
        print("用法: python hub_api.py status | sync [project_tag] | lock")
