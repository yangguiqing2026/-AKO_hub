"""
registry_client.py — AKO_registry_agent 客户端。

连接注册中心拉取 Agent 注册信息，写入路由表。
支持两种模式：
  1. HTTP 远程模式：连接 registry_agent 的 /agents 端点
  2. 本地 fallback：读取 registry/workflows.py 中的静态注册表
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.core.config_loader import HubConfig

logger = logging.getLogger("AKO_hub.registry_client")


class RegistryClient:
    """注册中心客户端，负责从 registry_agent 拉取 Agent 注册信息。"""

    def __init__(self, config: HubConfig) -> None:
        self.config = config
        self.endpoint = config.registry_endpoint.rstrip("/")
        self.timeout = config.registry_timeout
        self._cache: Dict[str, Dict[str, Any]] = {}

    def fetch_agents(self) -> Dict[str, Dict[str, Any]]:
        """
        从注册中心拉取全部 Agent 信息。

        Returns:
            {agent_id: agent_info_dict, ...}

        优先尝试 HTTP 远程连接，失败则回退到本地注册表。
        """
        # 模式 1：HTTP 远程
        agents = self._fetch_via_http()
        if agents:
            logger.info(f"远程拉取成功: {len(agents)} 个 Agent")
            self._cache = agents
            return agents

        # 模式 2：本地 fallback
        logger.warning("远程注册中心不可达，回退到本地注册表")
        agents = self._load_local_registry()
        logger.info(f"本地注册表加载: {len(agents)} 个 Agent")
        self._cache = agents
        return agents

    def _fetch_via_http(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """通过 HTTP 从 registry_agent 拉取。"""
        url = f"{self.endpoint}/agents"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            # 期望格式: {"agents": {agent_id: {...}, ...}}
            if isinstance(data, dict) and "agents" in data:
                return data["agents"]
            elif isinstance(data, dict):
                # 直接是 {agent_id: {...}, ...}
                return data
            else:
                logger.warning(f"注册中心返回格式异常: {type(data).__name__}")
                return None

        except requests.ConnectionError:
            logger.debug(f"连接失败: {url}")
            return None
        except requests.Timeout:
            logger.debug(f"连接超时 ({self.timeout}s): {url}")
            return None
        except Exception as e:
            logger.debug(f"HTTP 拉取异常: {e}")
            return None

    def _load_local_registry(self) -> Dict[str, Dict[str, Any]]:
        """从本地 registry/workflows.py 加载静态注册表。"""
        try:
            from registry.workflows import SPOKE_REGISTRY, list_all_spokes

            agents: Dict[str, Dict[str, Any]] = {}
            for spoke in list_all_spokes():
                agent_id = spoke["workflow_id"]
                agents[agent_id] = {
                    "agent_id": agent_id,
                    "name": spoke["name"],
                    "type": spoke["spoke_type"],
                    "entry_module": spoke["entry_module"],
                    "entry_function": spoke.get("entry_function", "run"),
                    "description": spoke.get("description", ""),
                    "source_dir": spoke.get("source_dir", ""),
                    "output_dir": spoke.get("output_dir", ""),
                    "invoke_mode": spoke.get("invoke_mode", "importlib"),
                    "required_kb_ids": spoke.get("required_kb_ids", []),
                    "status": spoke.get("status", "registered"),
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                    "last_heartbeat": None,
                    "load": 0,
                    "priority": 5,  # 默认优先级
                }
            return agents

        except ImportError as e:
            logger.error(f"本地注册表导入失败: {e}")
            return {}

    @property
    def cached_agents(self) -> Dict[str, Dict[str, Any]]:
        """返回最近一次拉取的缓存。"""
        return self._cache

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """从缓存中获取单个 Agent 信息。"""
        return self._cache.get(agent_id)
