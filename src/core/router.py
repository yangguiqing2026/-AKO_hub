"""
router.py — 消息路由器。

根据配置的路由策略，从路由表中选择合适的 Agent 处理请求。
支持三种策略：
  - round_robin: 轮询，依次分配
  - least_load: 最小负载，选择当前负载最低的 Agent
  - priority: 优先级，选择优先级最高（数值最小）的 Agent
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.config_loader import HubConfig
from src.core.routing_table import RoutingTable

logger = logging.getLogger("AKO_hub.router")


class MessageRouter:
    """消息路由器，根据策略从路由表中选择目标 Agent。"""

    STRATEGIES = ("round_robin", "least_load", "priority")

    def __init__(self, config: HubConfig, routing_table: RoutingTable) -> None:
        self.config = config
        self.table = routing_table
        self.strategy = config.routing_strategy

        if self.strategy not in self.STRATEGIES:
            logger.warning(f"未知策略 '{self.strategy}'，回退到 round_robin")
            self.strategy = "round_robin"

        logger.info(f"路由器初始化: 策略={self.strategy}")

    # ── 核心路由 ─────────────────────────────────────────────────

    def route(self, intent: str = "", target_agent: str = "") -> Optional[Dict[str, Any]]:
        """
        根据意图路由到一个 Agent。

        Args:
            intent: 任务意图（用于匹配 Agent 能力描述）
            target_agent: 指定目标 Agent ID（直连模式）

        Returns:
            选中的 Agent 信息 dict，或 None（无可用 Agent）
        """
        # 直连模式：指定了目标 Agent
        if target_agent:
            agent = self.table.get_agent(target_agent)
            if agent:
                logger.debug(f"直连路由 → {target_agent}")
                return agent
            else:
                logger.warning(f"指定 Agent 不存在: {target_agent}")
                return None

        # 获取候选 Agent（状态为 registered 或 active）
        candidates = self._get_candidates(intent)
        if not candidates:
            logger.warning("无可用 Agent")
            return None

        # 按策略选择
        if self.strategy == "round_robin":
            return self._route_round_robin(candidates)
        elif self.strategy == "least_load":
            return self._route_least_load(candidates)
        elif self.strategy == "priority":
            return self._route_priority(candidates)

        return None

    def route_many(self, intent: str = "", count: int = 1) -> List[Dict[str, Any]]:
        """
        路由到多个 Agent（用于并行分发）。

        Args:
            intent: 任务意图
            count: 需要选择的 Agent 数量

        Returns:
            选中的 Agent 信息列表
        """
        candidates = self._get_candidates(intent)
        if not candidates:
            return []

        selected: List[Dict[str, Any]] = []
        for _ in range(min(count, len(candidates))):
            agent = self.route(intent=intent)
            if agent and agent not in selected:
                selected.append(agent)

        return selected

    # ── 策略实现 ─────────────────────────────────────────────────

    def _route_round_robin(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """轮询策略：依次选择。"""
        agent_ids = [a["agent_id"] for a in candidates]
        chosen_id = self.table.next_rr_index(agent_ids)
        chosen = self.table.get_agent(chosen_id)
        logger.debug(f"round_robin → {chosen_id}")
        return chosen or candidates[0]

    def _route_least_load(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """最小负载策略：选择 load 值最低的 Agent。"""
        chosen = min(candidates, key=lambda a: a.get("load", 0))
        logger.debug(f"least_load → {chosen['agent_id']} (load={chosen.get('load', 0)})")
        return chosen

    def _route_priority(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """优先级策略：选择 priority 数值最小的 Agent（1=最高）。"""
        chosen = min(candidates, key=lambda a: a.get("priority", 99))
        logger.debug(f"priority → {chosen['agent_id']} (priority={chosen.get('priority', 99)})")
        return chosen

    # ── 辅助 ─────────────────────────────────────────────────────

    def _get_candidates(self, intent: str = "") -> List[Dict[str, Any]]:
        """
        获取候选 Agent 列表。

        当前返回所有已注册 Agent。
        未来可根据 intent 关键词匹配 Agent 能力描述进行过滤。
        """
        all_agents = list(self.table.agents.values())

        # 过滤掉 deprecated 的 Agent
        candidates = [
            a for a in all_agents
            if a.get("status") not in ("deprecated", "offline")
        ]

        # 如果 intent 非空，可按关键词做能力匹配（可选增强）
        if intent and candidates:
            # 简单关键词匹配：intent 中的词出现在 Agent description 中
            scored = []
            for agent in candidates:
                desc = agent.get("description", "").lower()
                score = sum(1 for word in intent.lower().split() if word in desc)
                scored.append((score, agent))

            # 如果有匹配的（score > 0），只返回匹配的
            matched = [a for s, a in scored if s > 0]
            if matched:
                return matched

        return candidates

    def update_agent_load(self, agent_id: str, load: int) -> None:
        """更新 Agent 负载值（用于 least_load 策略）。"""
        agent = self.table.get_agent(agent_id)
        if agent:
            agent["load"] = load

    def get_stats(self) -> Dict[str, Any]:
        """返回路由器统计信息。"""
        return {
            "strategy": self.strategy,
            "total_agents": self.table.agent_count,
            "online_agents": len(self.table.get_online_agents()),
            "last_sync": self.table.last_sync,
        }

    def __repr__(self) -> str:
        return f"MessageRouter(strategy={self.strategy!r}, agents={self.table.agent_count})"
