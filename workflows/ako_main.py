"""
AKO Hub — AKO 主工作流

文档编号: AGE-TECH-AKO-HUB-001 §6.3

职责：
    主编排工作流：可调度多个 Agent 协同执行。
    作为 LangGraph 子图，通过 compiled_graph 对象供 Master Graph 的 workflow_caller 节点调用。

调用链：
    Master Graph → workflows.ako_main.compiled_graph.invoke(payload)

工作流编排策略：
    1. 根据 intent 关键字调度对应 Agent（结构计算 → architect，图纸 → inspector，图像 → analyzer）。
    2. 若 intent 不匹配任何 Agent，返回提示信息。
    3. 支持 agent_list 参数显式指定要调度的 Agent 列表。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id


def run_workflow(
    intent: str = "",
    project_tag: str = "taoli",
    agent_list: Optional[List[str]] = None,
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    AKO 主工作流入口。

    Args:
        intent: 任务意图，用于关键词路由。
        project_tag: 项目标签。
        agent_list: 显式指定的 Agent 名称列表（可选，优先级高于 keyword 路由）。
        _hub_output_dir: Master Graph 下发的产出目录。
        _hub_db_path: 元数据库路径。
        _hub_chroma_root: Chroma 根目录。
        _hub_file_root: 文件总线根目录。
        **kwargs: 透传到子 Agent。

    Returns:
        {
            "output_files": [...],
            "summary": str,
            "error": str|None,
            "sub_results": [...]  # 各子 Agent 的执行结果
        }
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 确定要调度的 Agent ──────────────────────────────────────
    if agent_list:
        target_names = agent_list
    else:
        target_names = _route_by_intent(intent)

    if not target_names:
        return {
            "output_files": [],
            "summary": f"AKO 主工作流无法匹配意图：{intent}。请使用结构/图纸/图像等关键词。",
            "error": f"未匹配的意图: {intent}",
            "sub_results": [],
        }

    # ── 逐个调用 Agent（顺序执行） ───────────────────────────────
    all_files: List[str] = []
    sub_results: List[Dict[str, Any]] = []
    errors: List[str] = []

    for agent_name in target_names:
        spoke = _find_agent_by_name(agent_name)
        if spoke is None:
            errors.append(f"Agent 未注册: {agent_name}")
            continue

        entry_module = spoke.get("entry_module", "")
        if not entry_module:
            errors.append(f"Agent {agent_name} 缺少 entry_module")
            continue

        try:
            import importlib
            mod = importlib.import_module(entry_module)
            func = getattr(mod, "run", None)
            if func is None:
                errors.append(f"Agent {agent_name} 模块 {entry_module} 缺少 run() 函数")
                continue

            result = func(
                intent=intent,
                project_tag=project_tag,
                _hub_output_dir=str(output_dir),
                _hub_db_path=_hub_db_path,
                _hub_chroma_root=_hub_chroma_root,
                _hub_file_root=_hub_file_root,
                **kwargs,
            )
            sub_results.append({"agent": agent_name, "result": result})
            if result.get("output_files"):
                all_files.extend(result["output_files"])
            if result.get("error"):
                errors.append(f"{agent_name}: {result['error']}")

        except Exception as e:
            errors.append(f"Agent {agent_name} 调用异常: {type(e).__name__}: {e}")

    # ── 生成聚合报告 ───────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"ako_workflow_report_{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "intent": intent,
                "project_tag": project_tag,
                "agents_called": target_names,
                "sub_results": sub_results,
                "errors": errors,
                "generated_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    all_files.append(str(report_path))

    summary = f"AKO 主工作流完成：调度 {len(target_names)} 个 Agent，产出 {len(all_files)} 个文件"
    if errors:
        summary += f"，{len(errors)} 个错误"

    return {
        "output_files": all_files,
        "summary": summary,
        "error": "; ".join(errors) if errors else None,
        "sub_results": sub_results,
    }


def _route_by_intent(intent: str) -> List[str]:
    """根据意图关键词路由到对应 Agent（返回 workflow_id）。"""
    intent_lower = intent.lower()

    if any(kw in intent_lower for kw in ["结构", "计算", "荷载", "构件", "设计"]):
        return ["AKO_architect_agent"]
    if any(kw in intent_lower for kw in ["图纸", "质检", "审查", "标注"]):
        return ["AKO_drawing_inspector"]
    if any(kw in intent_lower for kw in ["图像", "分析", "缺陷", "识别"]):
        return ["AKO_image_analyzer_agent"]
    if "编排" in intent_lower or "全流程" in intent_lower:
        return ["AKO_architect_agent", "AKO_drawing_inspector", "AKO_image_analyzer_agent"]

    return []


def _find_agent_by_name(name: str) -> Optional[Dict[str, Any]]:
    """根据 workflow_id 在注册表中查找 Spoke。"""
    return get_spoke_by_id(name)


# ── LangGraph 子图入口（供 Master Graph 的 workflow_caller 调用） ─
# 由于 AKO 主工作流使用按需 importlib 加载模式而非预编译 LangGraph 子图，
# 这里暴露一个包装后的 graph 对象，使其兼容 workflow_caller 的调用方式。

class _WorkflowGraphWrapper:
    """将 run_workflow 函数包装为类 LangGraph 子图对象。"""

    def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return run_workflow(**payload)


compiled_graph = _WorkflowGraphWrapper()
"""供 Master Graph workflow_caller 调用的编译图对象。"""


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ret = run_workflow(intent="全流程", project_tag="taoli", _hub_output_dir=td)
        print(json.dumps(ret, ensure_ascii=False, indent=2))