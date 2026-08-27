"""
task_executor.py — DAG 任务执行器。

根据 TaskNode 依赖关系进行拓扑排序，按序调用各 Agent 子进程，
汇总执行结果。文档编号: AGE-TECH-AKO-HUB-022 §TaskExecutor
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 常量 ───────────────────────────────────────────────────────────
DEFAULT_DB_PATH: str = "ako_hub.db"
DB_TIMEOUT: float = 5.0
SUBPROCESS_TIMEOUT: int = 300            # 单个子任务超时（秒）
DEFAULT_PYTHON: str = sys.executable     # 当前 Python 解释器


# ── SPOKE 注册表（Agent ID → 可执行入口） ──────────────────────────
# 子进程调用约定: {python} {entry_script} < stdin.json > stdout.json
# 完成后写 _DONE.json 到工作目录
SPOKE_REGISTRY: Dict[str, Dict[str, str]] = {
    "AKO_chat":                 {"entry": "agents/ako_chat_adapter.py",       "type": "script"},
    "AKO_quote_agent":          {"entry": "agents/ako_quote_adapter.py",      "type": "script"},
    "AKO_layout_agent":         {"entry": "agents/ako_layout_adapter.py",     "type": "script"},
    "AKO_media_agent":          {"entry": "agents/ako_media_adapter.py",      "type": "script"},
    "AKO_drawing_inspector":    {"entry": "agents/ako_drawing_inspector.py",  "type": "script"},
    "AKO_image_analyzer_agent": {"entry": "agents/ako_image_analyzer.py",     "type": "script"},
    "AKO_architect_agent":      {"entry": "agents/ako_architect_adapter.py",  "type": "script"},
    "AKO_reports":              {"entry": "agents/ako_reports_adapter.py",    "type": "script"},
    "AKO_form_extractor":       {"entry": "agents/ako_form_extractor_adapter.py", "type": "script"},
    "AKO_netwatch_agent":       {"entry": "agents/ako_netwatch_adapter.py",   "type": "script"},
    "AKO_business_agent":       {"entry": "agents/ako_business_adapter.py",   "type": "script"},
    "AKO_knowledge":            {"entry": "agents/ako_knowledge_adapter.py",  "type": "script"},
    "AKO_law_agent":            {"entry": "agents/ako_law_adapter.py",        "type": "script"},
    "AKO_geo":                  {"entry": "agents/ako_geo_adapter.py",        "type": "script"},
    "AKO工作流":                 {"entry": "agents/ako_workflow_adapter.py",  "type": "script"},
}


@dataclass
class TaskNode:
    """单个任务节点，表示一次 Agent 调用。"""

    agent_id: str                           # 目标 Agent ID
    intent: str = ""                        # 意图描述
    inputs: Dict[str, Any] = field(default_factory=dict)   # 输入参数
    dependencies: List[str] = field(default_factory=list)   # 依赖的 agent_id 列表
    status: str = "pending"                 # pending | running | done | failed


class TaskExecutor:
    """
    DAG 任务执行器。

    接收 IntentRouter.build_execution_plan() 产出的 TaskNode 列表，
    按拓扑顺序依次执行，每个节点收到上游节点的输出作为额外输入。

    Usage:
        executor = TaskExecutor()
        result = executor.execute(plan)
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """
        Args:
            db_path: SQLite 数据库路径（用于记录执行日志）
        """
        self.db_path: str = db_path
        self.trace_id: str = ""
        self._node_results: Dict[str, Dict[str, Any]] = {}

    def execute(self, plan: List[TaskNode]) -> Dict[str, Any]:
        """
        按拓扑顺序执行任务计划。

        Args:
            plan: 有序 TaskNode 列表（通常由 IntentRouter 产出）

        Returns:
            {
                "trace_id": str,
                "results": {agent_id: output_dict, ...},
                "final_output": Any,          # 最后一个节点的输出
                "status": "success" | "partial" | "failed",
            }
        """
        self.trace_id = str(uuid.uuid4())[:8]
        self._node_results.clear()

        if not plan:
            return {
                "trace_id": self.trace_id,
                "results": {},
                "final_output": None,
                "status": "failed",
                "error": "空计划",
            }

        # 1) 拓扑排序（已经是排好序的，但做一个校验）
        sorted_nodes = self._topological_sort(plan)

        # 2) 按序执行
        failed_count = 0
        for node in sorted_nodes:
            result = self._execute_node(node)
            self._node_results[node.agent_id] = result
            if result.get("status") == "failed":
                failed_count += 1
                # 下游节点标记为 blocked
                self._mark_downstream_blocked(sorted_nodes, node.agent_id)

        # 3) 确定最终状态
        if failed_count == 0:
            overall = "success"
        elif failed_count < len(sorted_nodes):
            overall = "partial"
        else:
            overall = "failed"

        # 4) 最终节点的输出
        final_node = sorted_nodes[-1]
        final_output = self._node_results.get(final_node.agent_id, {})

        return {
            "trace_id": self.trace_id,
            "results": dict(self._node_results),
            "final_output": final_output.get("data"),
            "status": overall,
        }

    # ── 拓扑排序 ─────────────────────────────────────────────────────

    def _topological_sort(self, nodes: List[TaskNode]) -> List[TaskNode]:
        """
        Kahn 算法拓扑排序，确保依赖关系正确。

        若存在环，返回原顺序并记录警告。

        Args:
            nodes: 原始 TaskNode 列表

        Returns:
            拓扑排序后的 TaskNode 列表
        """
        if not nodes:
            return []

        name_to_idx = {n.agent_id: i for i, n in enumerate(nodes)}
        in_degree = [0] * len(nodes)
        adj: List[List[int]] = [[] for _ in range(len(nodes))]

        # 建立图
        for i, node in enumerate(nodes):
            for dep_id in node.dependencies:
                if dep_id in name_to_idx:
                    dep_idx = name_to_idx[dep_id]
                    adj[dep_idx].append(i)
                    in_degree[i] += 1

        # Kahn BFS
        q: deque = deque(i for i, d in enumerate(in_degree) if d == 0)
        order: List[int] = []

        while q:
            u = q.popleft()
            order.append(u)
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    q.append(v)

        if len(order) != len(nodes):
            # 存在环 → 回退原顺序
            return list(nodes)

        return [nodes[i] for i in order]

    # ── 单节点执行 ───────────────────────────────────────────────────

    def _execute_node(self, node: TaskNode) -> Dict[str, Any]:
        """
        执行单个 TaskNode。

        合并依赖节点的输出到 inputs，通过子进程调用目标 Agent。

        Args:
            node: 待执行的 TaskNode

        Returns:
            {"status": "success"|"failed", "data": ..., "error": ...}
        """
        node.status = "running"

        # 合并上游输出
        merged_inputs = dict(node.inputs)
        for dep_id in node.dependencies:
            dep_result = self._node_results.get(dep_id, {})
            if dep_result.get("status") == "success":
                merged_inputs[f"_from_{dep_id}"] = dep_result.get("data")

        spoke = SPOKE_REGISTRY.get(node.agent_id)
        if not spoke:
            node.status = "failed"
            return {
                "status": "failed",
                "error": f"未知 Agent: {node.agent_id}",
                "data": None,
            }

        entry_path = PROJECT_ROOT / spoke["entry"]
        if not entry_path.exists():
            node.status = "failed"
            return {
                "status": "failed",
                "error": f"Agent 入口不存在: {entry_path}",
                "data": None,
            }

        # 构建子进程调用参数
        payload = {
            "trace_id": self.trace_id,
            "agent_id": node.agent_id,
            "intent": node.intent,
            "inputs": merged_inputs,
        }

        try:
            proc = subprocess.run(
                [DEFAULT_PYTHON, "-X", "utf8", str(entry_path)],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
                cwd=str(PROJECT_ROOT),
            )

            if proc.returncode != 0:
                node.status = "failed"
                return {
                    "status": "failed",
                    "error": proc.stderr.strip() or f"进程退出码 {proc.returncode}",
                    "data": proc.stdout.strip() if proc.stdout else None,
                }

            stdout = proc.stdout.strip()
            if not stdout:
                node.status = "done"
                return {"status": "success", "data": None}

            # 尝试解析 JSON 输出
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                data = stdout

            node.status = "done"
            return {"status": "success", "data": data}

        except subprocess.TimeoutExpired:
            node.status = "failed"
            return {
                "status": "failed",
                "error": f"子进程超时（>{SUBPROCESS_TIMEOUT}s）",
                "data": None,
            }
        except Exception as exc:
            node.status = "failed"
            return {
                "status": "failed",
                "error": str(exc),
                "data": None,
            }

    # ── 辅助 ─────────────────────────────────────────────────────────

    def _mark_downstream_blocked(
        self, nodes: List[TaskNode], failed_agent_id: str
    ) -> None:
        """将依赖失败节点的下游节点标记为 blocked。"""
        for node in nodes:
            if failed_agent_id in node.dependencies and node.status == "pending":
                node.status = "blocked"


# ── 自检 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 简单拓扑排序测试
    executor = TaskExecutor()

    n1 = TaskNode(agent_id="A", dependencies=[])
    n2 = TaskNode(agent_id="B", dependencies=["A"])
    n3 = TaskNode(agent_id="C", dependencies=["A"])
    n4 = TaskNode(agent_id="D", dependencies=["B", "C"])

    sorted_nodes = executor._topological_sort([n4, n2, n3, n1])
    order = [n.agent_id for n in sorted_nodes]
    print(f"拓扑排序: {order}")
    assert order[0] == "A", f"Expected A first, got {order[0]}"
    assert order[-1] == "D", f"Expected D last, got {order[-1]}"
    print("拓扑排序测试通过")
