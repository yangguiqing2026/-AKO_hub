"""
config_loader.py — AKO_hub 配置加载器。

读取 config/AKO_hub_config.yaml，提供类型安全的配置访问接口。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger("AKO_hub.config")


class HubConfig:
    """AKO_hub 配置封装，提供结构化访问各配置段。"""

    def __init__(self, raw: Dict[str, Any], config_path: str = "") -> None:
        self._raw = raw
        self._config_path = config_path

    # ── 原始访问 ──────────────────────────────────────────────────

    @property
    def raw(self) -> Dict[str, Any]:
        return self._raw

    # ── Agent 基本信息 ────────────────────────────────────────────

    @property
    def agent_id(self) -> str:
        return self._raw.get("agent", {}).get("id", "AKO_hub")

    @property
    def agent_name(self) -> str:
        return self._raw.get("agent", {}).get("name", "AKO Hub")

    @property
    def log_level(self) -> str:
        return self._raw.get("agent", {}).get("log_level", "INFO")

    # ── 注册中心 ─────────────────────────────────────────────────

    @property
    def registry_agent_id(self) -> str:
        return self._raw.get("registry", {}).get("agent_id", "AKO_registry_agent")

    @property
    def registry_endpoint(self) -> str:
        return self._raw.get("registry", {}).get("endpoint", "http://localhost:PORT")

    @property
    def registry_sync_interval(self) -> int:
        return self._raw.get("registry", {}).get("sync_interval", 60)

    @property
    def registry_timeout(self) -> int:
        return self._raw.get("registry", {}).get("timeout", 10)

    # ── 路由策略 ─────────────────────────────────────────────────

    @property
    def routing_strategy(self) -> str:
        return self._raw.get("routing", {}).get("strategy", "round_robin")

    @property
    def routing_timeout(self) -> int:
        return self._raw.get("routing", {}).get("timeout", 30)

    @property
    def routing_retry_count(self) -> int:
        return self._raw.get("routing", {}).get("retry_count", 3)

    @property
    def routing_retry_backoff(self) -> int:
        return self._raw.get("routing", {}).get("retry_backoff", 2)

    # ── 健康检查 ─────────────────────────────────────────────────

    @property
    def health_check_interval(self) -> int:
        return self._raw.get("health_check", {}).get("interval", 30)

    @property
    def health_check_timeout(self) -> int:
        return self._raw.get("health_check", {}).get("timeout", 5)

    @property
    def health_check_failure_threshold(self) -> int:
        return self._raw.get("health_check", {}).get("failure_threshold", 3)

    # ── 消息队列 ─────────────────────────────────────────────────

    @property
    def mq_type(self) -> str:
        return self._raw.get("message_queue", {}).get("type", "memory")

    @property
    def mq_max_size(self) -> int:
        return self._raw.get("message_queue", {}).get("max_size", 10000)

    # ── 存储路径 ─────────────────────────────────────────────────

    @property
    def routing_table_path(self) -> str:
        return self._raw.get("storage", {}).get("routing_table", "data/routing_table.json")

    @property
    def agent_state_path(self) -> str:
        return self._raw.get("storage", {}).get("agent_state", "data/agent_state.json")

    # ── 日志配置 ─────────────────────────────────────────────────

    @property
    def logging_path(self) -> str:
        return self._raw.get("logging", {}).get("path", "logs/hub.log")

    @property
    def logging_format(self) -> str:
        return self._raw.get("logging", {}).get(
            "format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    def __repr__(self) -> str:
        return f"HubConfig(agent_id={self.agent_id!r}, strategy={self.routing_strategy!r})"


def load_config(config_path: str = "config/AKO_hub_config.yaml") -> HubConfig:
    """
    从 YAML 文件加载配置。

    Args:
        config_path: 配置文件路径（相对于项目根目录或绝对路径）

    Returns:
        HubConfig 实例

    Raises:
        FileNotFoundError: 配置文件不存在
        yaml.YAMLError: YAML 解析失败
    """
    path = Path(config_path)
    if not path.is_absolute():
        # 相对于项目根目录
        project_root = Path(__file__).resolve().parent.parent.parent
        path = project_root / path

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    logger.info(f"加载配置: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件格式错误，期望 dict，实际 {type(raw).__name__}")

    cfg = HubConfig(raw, config_path=str(path))
    logger.info(f"配置加载完成: agent_id={cfg.agent_id}, strategy={cfg.routing_strategy}")
    return cfg
