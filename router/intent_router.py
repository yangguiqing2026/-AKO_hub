"""
intent_router.py — 核心路由引擎。

接收用户输入，通过关键词匹配 + 规则引擎确定目标 Agent 和执行计划。
文档编号: AGE-TECH-AKO-HUB-021 §IntentRouter
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from registry.taxonomy import (
    get_domain,
    get_function,
    get_category,
    list_by_domain,
    list_by_function,
    find_unclassified,
)
from registry.workflows import list_spokes_enriched, list_unclassified
from router.task_executor import TaskNode


# ── 常量 ───────────────────────────────────────────────────────────
DEFAULT_DB_PATH: str = "ako_hub.db"
DEFAULT_RULES_PATH: str = "config/routing_rules.yaml"
INIT_RECONNECT_DELAY: float = 0.5
DB_TIMEOUT: float = 5.0
CONFIDENCE_THRESHOLD: float = 0.6            # 置信度及格线


# ── 内置关键词路由表（YAML 的 fallback） ─────────────────────────
_FALLBACK_ROUTING: Dict[str, Dict[str, Any]] = {
    "报价":      {"agent_id": "AKO_quote_agent",     "confidence": 0.95},
    "报价单":    {"agent_id": "AKO_quote_agent",     "confidence": 0.95},
    "报价计算":  {"agent_id": "AKO_quote_agent",     "confidence": 0.95},
    "文案":      {"agent_id": "AKO_media_agent",     "confidence": 0.90},
    "推文":      {"agent_id": "AKO_media_agent",     "confidence": 0.90},
    "公众号":    {"agent_id": "AKO_media_agent",     "confidence": 0.90},
    "热点":      {"agent_id": "AKO_media_agent",     "confidence": 0.85},
    "配图":      {"agent_id": "AKO_layout_agent",    "confidence": 0.80},
    "排版":      {"agent_id": "AKO_layout_agent",    "confidence": 0.80},
    "布局":      {"agent_id": "AKO_layout_agent",    "confidence": 0.80},
    "草图":      {"agent_id": "AKO_layout_agent",    "confidence": 0.85},
    "图纸":      {"agent_id": "AKO_drawing_inspector","confidence": 0.90},
    "审图":      {"agent_id": "AKO_drawing_inspector","confidence": 0.95},
    "分析":      {"agent_id": "AKO_image_analyzer_agent",  "confidence": 0.70},
    "图像":      {"agent_id": "AKO_image_analyzer_agent",  "confidence": 0.80},
    "设计":      {"agent_id": "AKO_architect_agent", "confidence": 0.75},
    "建筑":      {"agent_id": "AKO_architect_agent", "confidence": 0.80},
    "报表":      {"agent_id": "AKO_reports",         "confidence": 0.90},
    "报告":      {"agent_id": "AKO_reports",         "confidence": 0.85},
    "表单":      {"agent_id": "AKO_form_extractor",  "confidence": 0.85},
    "提取":      {"agent_id": "AKO_form_extractor",  "confidence": 0.75},
    "监控":      {"agent_id": "AKO_netwatch_agent",  "confidence": 0.85},
    "网络":      {"agent_id": "AKO_netwatch_agent",  "confidence": 0.80},
    "商业":      {"agent_id": "AKO_business_agent",  "confidence": 0.80},
    "聊天":      {"agent_id": "AKO_chat",            "confidence": 0.85},
    "问答":      {"agent_id": "AKO_chat",            "confidence": 0.80},
    "知识":      {"agent_id": "AKO_knowledge",       "confidence": 0.80},
    "写作":      {"agent_id": "AKO_writer_agent",     "confidence": 0.85},
    "文章":      {"agent_id": "AKO_writer_agent",     "confidence": 0.85},
    "检索":      {"agent_id": "AKO_knowledge",       "confidence": 0.85},
}


class IntentRouter:
    """
    意图路由引擎。

    职责：
    1. parse_intent() — 关键词匹配 → 返回最匹配的 Agent
    2. build_execution_plan() — 查 YAML 复合任务规则 → 生成 DAG
    3. execute_plan() — 串联 TaskExecutor 编排执行

    用法:
        router = IntentRouter()
        result = router.parse_intent("帮我算一下这个项目报价")
        plan = router.build_execution_plan(result, context={})
        outcome = router.execute_plan(plan)
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        rules_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            db_path: SQLite 数据库路径（用于读取能力注册表）
            rules_path: routing_rules.yaml 路径，默认 config/routing_rules.yaml
        """
        self.db_path: str = db_path
        self.rules_path: Path = PROJECT_ROOT / (rules_path or DEFAULT_RULES_PATH)

        # ── 路由规则缓存 ──
        self._keyword_routing: Dict[str, Dict[str, Any]] = dict(_FALLBACK_ROUTING)
        self._composite_tasks: List[Dict[str, Any]] = []
        self._rules_mtime: float = 0.0

        # ── 加载 YAML 规则 ──
        self._load_rules()

        # ── 初始化 DB ──
        self._init_db()

    # ── 公开方法 ───────────────────────────────────────────────────

    def parse_intent(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        解析用户输入，返回最佳匹配的 Agent 意图。

        Args:
            user_input: 用户自然语言输入
            context: 可选上下文（如历史对话、项目信息等）

        Returns:
            {
                "intent": str,          # 识别的意图关键词
                "agent_id": str,        # 目标 Agent ID
                "confidence": float,    # 置信度 (0.0-1.0)
                "dependencies": list,   # 依赖的其他 Agent（复合任务时）
                "estimated_time": int,  # 预估耗时（秒）
            }
        """
        context = context or {}
        user_input = user_input.strip()

        if not user_input:
            return self._no_match_result()

        # 1) 复合任务优先级匹配
        composite_match = self._match_composite(user_input)
        if composite_match and composite_match.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            return composite_match

        # 2) 关键词匹配
        best_score = 0.0
        best_agent: Optional[str] = None
        best_keyword: str = ""

        for keyword, rule in self._keyword_routing.items():
            if keyword in user_input:
                score = rule.get("confidence", 0.5)
                # 加权：更长的关键词匹配加分
                score += len(keyword) * 0.005
                if score > best_score:
                    best_score = score
                    best_agent = rule["agent_id"]
                    best_keyword = keyword

        if best_agent and best_score >= CONFIDENCE_THRESHOLD:
            return {
                "intent": best_keyword,
                "agent_id": best_agent,
                "confidence": round(min(best_score, 1.0), 3),
                "dependencies": [],
                "estimated_time": 10,
            }

        # 3) 关键词折半匹配（模糊）
        for keyword, rule in self._keyword_routing.items():
            if len(keyword) >= 2 and keyword[:2] in user_input:
                score = rule.get("confidence", 0.5) * 0.7
                if score > best_score:
                    best_score = score
                    best_agent = rule["agent_id"]
                    best_keyword = keyword

        if best_agent and best_score >= 0.4:
            return {
                "intent": best_keyword,
                "agent_id": best_agent,
                "confidence": round(min(best_score, 1.0), 3),
                "dependencies": [],
                "estimated_time": 10,
            }

        # 4) 无匹配 → 回退到 chat Agent
        return {
            "intent": "通用问答",
            "agent_id": "AKO_chat",
            "confidence": 0.35,
            "dependencies": [],
            "estimated_time": 5,
        }

    def build_execution_plan(
        self, intent_result: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> List[TaskNode]:
        """
        将意图结果展开为有序的 TaskNode 列表。

        先查 YAML composite_tasks，若命中则按 sequence 生成 DAG；
        否则返回单节点计划。

        Args:
            intent_result: parse_intent() 的返回值
            context: 附加上下文（用户原始输入、项目信息等）

        Returns:
            拓扑排序后的 TaskNode 列表
        """
        context = context or {}
        user_input = context.get("user_input", intent_result.get("intent", ""))

        # 查复合任务匹配
        composite = self._match_composite(user_input)
        if composite and composite.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            return self._plan_from_composite(composite, context)

        # 单任务计划
        node = TaskNode(
            agent_id=intent_result.get("agent_id", "AKO_chat"),
            intent=intent_result.get("intent", ""),
            inputs={
                "user_input": user_input,
                **context,
            },
            dependencies=[],
        )
        return [node]

    def execute_plan(self, plan: List[TaskNode]) -> Dict[str, Any]:
        """
        执行任务计划。

        委托给 TaskExecutor 按拓扑顺序执行，汇总结果。

        Args:
            plan: build_execution_plan() 返回的 TaskNode 列表

        Returns:
            {
                "trace_id": str,
                "results": Dict[str, Any],   # agent_id → 输出
                "final_output": Any,         # 最终节点的输出
            }
        """
        from router.task_executor import TaskExecutor

        executor = TaskExecutor(db_path=self.db_path)
        return executor.execute(plan)

    # ── 分类感知（三维分类学） ──────────────────────────────────

    def agents_in_domain(self, domain: str) -> List[str]:
        """返回属于某业务域的全部 Agent（workflow_id 列表）。"""
        return list_by_domain(domain)

    def agents_by_function(self, function: str) -> List[str]:
        """返回属于某功能类型的全部 Agent（workflow_id 列表）。"""
        return list_by_function(function)

    def classify(self, agent_id: str) -> Dict[str, Any]:
        """返回单个 Agent 的三维分类。"""
        return {
            "agent_id": agent_id,
            "domain": get_domain(agent_id),
            "function": get_function(agent_id),
            "category": get_category(agent_id),
        }

    def taxonomy_map(self) -> Dict[str, Dict[str, str]]:
        """返回全部已注册 Agent 的分类映射。"""
        return {
            s["workflow_id"]: {
                "domain": s.get("domain", ""),
                "function": s.get("function", ""),
                "category": s.get("category", ""),
            }
            for s in list_spokes_enriched()
        }

    def unclassified_agents(self) -> List[str]:
        """列出「未分类」的 Agent。供巡检/自检调用。"""
        return list_unclassified()

    def register_capabilities(self, agent_id: str, capabilities_json: str) -> None:
        """
        注册/更新 Agent 能力描述。

        Args:
            agent_id: Agent 唯一标识
            capabilities_json: JSON 字符串，格式:
                {
                    "keywords": ["报价", "价格", ...],
                    "description": "...",
                    "input_schema": {...},
                    "output_schema": {...}
                }
        """
        try:
            caps = json.loads(capabilities_json)
        except json.JSONDecodeError:
            caps = {"raw": capabilities_json}

        keywords = caps.get("keywords", [])
        description = caps.get("description", "")

        conn = sqlite3.connect(
            str(PROJECT_ROOT / self.db_path), timeout=DB_TIMEOUT
        )
        try:
            conn.execute("""
                INSERT INTO agent_capabilities (agent_id, description, keywords, input_schema, output_schema, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    description = excluded.description,
                    keywords = excluded.keywords,
                    input_schema = excluded.input_schema,
                    output_schema = excluded.output_schema,
                    updated_at = excluded.updated_at
            """, (
                agent_id,
                description,
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(caps.get("input_schema", {}), ensure_ascii=False),
                json.dumps(caps.get("output_schema", {}), ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

        # 同步到内存路由表
        for kw in keywords:
            if kw and kw not in self._keyword_routing:
                self._keyword_routing[kw] = {"agent_id": agent_id, "confidence": 0.7}

    # ── 内部：规则加载 ─────────────────────────────────────────────

    def _load_rules(self) -> None:
        """从 YAML 文件加载路由规则（含热加载检查）。"""
        if not self.rules_path.exists():
            return

        try:
            mtime = self.rules_path.stat().st_mtime
            if mtime == self._rules_mtime:
                return   # 未变化，跳过

            import yaml
            with open(self.rules_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            # 加载复合任务
            self._composite_tasks = config.get("composite_tasks", [])

            # 加载关键词路由（合并到 fallback）
            for entry in config.get("keyword_routes", []):
                kw = entry.get("keyword", "")
                if kw:
                    self._keyword_routing[kw] = {
                        "agent_id": entry.get("agent_id", ""),
                        "confidence": entry.get("confidence", 0.8),
                    }

            self._rules_mtime = mtime

        except Exception:
            # YAML 解析失败则用 fallback
            pass

    def _init_db(self) -> None:
        """确保能力注册表存在。"""
        db_full = PROJECT_ROOT / self.db_path
        conn = sqlite3.connect(str(db_full), timeout=DB_TIMEOUT)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_capabilities (
                    agent_id      TEXT PRIMARY KEY,
                    description   TEXT NOT NULL DEFAULT '',
                    keywords      TEXT NOT NULL DEFAULT '[]',
                    input_schema  TEXT NOT NULL DEFAULT '{}',
                    output_schema TEXT NOT NULL DEFAULT '{}',
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ── 内部：匹配逻辑 ─────────────────────────────────────────────

    def _match_composite(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        匹配复合任务规则。

        规则中的 trigger 支持 AND / OR 简单布尔逻辑：
        "报价 AND (复杂 OR 非标 OR 特殊)"
        """
        best: Optional[Dict[str, Any]] = None
        best_score = 0.0

        for task_def in self._composite_tasks:
            trigger: str = task_def.get("trigger", "")
            score = self._evaluate_trigger(trigger, user_input)
            if score > best_score and score >= CONFIDENCE_THRESHOLD:
                best_score = score
                agents_in_seq = [
                    step.get("agent", "") for step in task_def.get("sequence", [])
                ]
                best = {
                    "intent": task_def.get("name", "复合任务"),
                    "agent_id": agents_in_seq[-1] if agents_in_seq else "",
                    "confidence": round(score, 3),
                    "dependencies": agents_in_seq[:-1] if len(agents_in_seq) > 1 else [],
                    "estimated_time": len(task_def.get("sequence", [])) * 15,
                    "_composite_def": task_def,
                }

        return best

    def _evaluate_trigger(self, trigger: str, user_input: str) -> float:
        """
        评估 trigger 字符串在当前输入下的匹配度。

        支持: keyword AND (k1 OR k2)，简单布尔表达式。
        返回: 0.0-1.0 置信度。
        """
        if not trigger:
            return 0.0

        # 拆分 AND 子句
        and_parts = re.split(r"\s+AND\s+", trigger, flags=re.IGNORECASE)
        scores: List[float] = []

        for part in and_parts:
            part = part.strip()
            # 检查是否有 OR 组
            or_match = re.match(r"\((.+)\)", part)
            if or_match:
                or_keywords = [
                    kw.strip() for kw in or_match.group(1).split("OR")
                ]
                or_score = 0.0
                for kw in or_keywords:
                    if kw and kw in user_input:
                        or_score = max(or_score, 0.9)
                scores.append(or_score)
            else:
                # 单关键词
                if part and part in user_input:
                    scores.append(0.9)
                else:
                    scores.append(0.0)

        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def _plan_from_composite(
        self, composite: Dict[str, Any], context: Dict[str, Any]
    ) -> List[TaskNode]:
        """从复合任务定义生成 TaskNode 列表。"""
        task_def = composite.get("_composite_def", {})
        sequence = task_def.get("sequence", [])
        nodes: List[TaskNode] = []
        prev_agent: Optional[str] = None

        for step in sequence:
            agent_id = step.get("agent", "")
            node = TaskNode(
                agent_id=agent_id,
                intent=step.get("action", ""),
                inputs={
                    **(step.get("inputs") or {}),
                    "user_input": context.get("user_input", ""),
                },
                dependencies=[prev_agent] if prev_agent else [],
            )
            nodes.append(node)
            prev_agent = agent_id

        return nodes

    @staticmethod
    def _no_match_result() -> Dict[str, Any]:
        return {
            "intent": "",
            "agent_id": "",
            "confidence": 0.0,
            "dependencies": [],
            "estimated_time": 0,
        }


# ── 自检 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    router = IntentRouter()

    tests = [
        "帮我算一下项目报价",
        "这个报价单有点复杂，帮我处理",
        "写一篇公众号推文",
        "审一下这张图纸",
        "帮我分析这张图片",
        "抽一下表单数据",
        "给我生成一份周报",
        "查询建筑规范",
    ]

    for t in tests:
        result = router.parse_intent(t)
        print(f"  '{t}' → {result['agent_id']} ({result['confidence']:.2f})")
