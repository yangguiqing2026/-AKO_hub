"""
routing_table.py — 路由表管理器。

管理 data/routing_table.json 的读写，
将 RegistryClient 拉取的 Agent 信息持久化为路由表。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AKO_hub.routing_table")


class RoutingTable:
    """路由表管理器，负责读写和查询路由表。"""

    def __init__(self, table_path: str = "data/routing_table.json") -> None:
        self.table_path = Path(table_path)
        if not self.table_path.is_absolute():
            project_root = Path(__file__).resolve().parent.parent.parent
            self.table_path = project_root / self.table_path

        self._data: Dict[str, Any] = {
            "version": "2.0.0",
            "generated": "",
            "author": "AKO_studio",
            "agents": {},
            "routes": {},
            "last_sync": None,
        }
        self._rr_index: int = 0  # round_robin 计数器

    # ── 加载 / 保存 ──────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """从磁盘加载路由表。"""
        if self.table_path.exists():
            with open(self.table_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info(f"路由表已加载: {self.table_path} ({len(self._data.get('agents', {}))} 个 Agent)")
        else:
            logger.warning(f"路由表文件不存在: {self.table_path}，使用空表")
        return self._data

    def save(self) -> None:
        """将路由表写入磁盘。"""
        self.table_path.parent.mkdir(parents=True, exist_ok=True)
        self._data["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._data["last_sync"] = datetime.now(timezone.utc).isoformat()

        with open(self.table_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

        logger.info(f"路由表已保存: {self.table_path} ({len(self._data.get('agents', {}))} 个 Agent)")

    # ── 同步（从 RegistryClient 写入） ───────────────────────────

    def sync_from_agents(self, agents: Dict[str, Dict[str, Any]]) -> int:
        """
        从 RegistryClient 拉取的 Agent 数据同步到路由表。

        Args:
            agents: {agent_id: agent_info_dict, ...}

        Returns:
            同步的 Agent 数量
        """
        self._data["agents"] = agents

        # 自动生成路由映射
        routes: Dict[str, str] = {}
        for agent_id, info in agents.items():
            routes[agent_id] = agent_id  # 1:1 直连路由

        self._data["routes"] = routes
        self._data["last_sync"] = datetime.now(timezone.utc).isoformat()

        count = len(agents)
        logger.info(f"路由表同步完成: {count} 个 Agent")
        return count

    # ── 查询 ─────────────────────────────────────────────────────

    @property
    def agents(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("agents", {})

    @property
    def routes(self) -> Dict[str, str]:
        return self._data.get("routes", {})

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def last_sync(self) -> Optional[str]:
        return self._data.get("last_sync")

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取单个 Agent 信息。"""
        return self.agents.get(agent_id)

    def list_agent_ids(self) -> List[str]:
        """列出所有 Agent ID。"""
        return list(self.agents.keys())

    def get_online_agents(self) -> List[Dict[str, Any]]:
        """获取在线（有心跳）的 Agent 列表。"""
        return [
            info for info in self.agents.values()
            if info.get("last_heartbeat") is not None
        ]

    def get_agents_by_status(self, status: str) -> List[Dict[str, Any]]:
        """按状态筛选 Agent。"""
        return [
            info for info in self.agents.values()
            if info.get("status") == status
        ]

    # ── Round-Robin 计数器 ───────────────────────────────────────

    def next_rr_index(self, candidates: List[str]) -> str:
        """
        Round-Robin 选择下一个 Agent。

        Args:
            candidates: 候选 Agent ID 列表

        Returns:
            选中的 Agent ID
        """
        if not candidates:
            return ""
        idx = self._rr_index % len(candidates)
        self._rr_index += 1
        return candidates[idx]

    def __repr__(self) -> str:
        return f"RoutingTable(agents={self.agent_count}, last_sync={self.last_sync!r})"
