"""
AKO 统一配置包 — 全系统唯一配置入口

设计原则：
  - hub.yaml  = 路径 / 模型 / 检索 / 端口 / 集合名等**非敏感配置**的唯一来源
  - .env      = API Key 等**敏感配置**的唯一来源
  - 各 Spoke 通过 get_config() 获取基础配置，再叠加 spoke_overlay()（可选）

用法：
    from core.ako_config import get_config

    cfg = get_config()
    cfg.hub_root           # Hub 同步根目录
    cfg.chroma_root        # ChromaDB 向量库根目录
    cfg.embedding_model    # "bge-m3"
    cfg.retrieval.mode     # "hybrid"
    cfg.retrieval.weights  # {"dense": 0.33, "sparse": 0.33, "colbert": 0.34}
    cfg.hub_url            # "http://127.0.0.1:7862"
    cfg.service_url("chat") # "http://localhost:7861"
    cfg.api_key("deepseek") # 从 .env 读取

Spoke 覆盖:
    spoke_cfg = cfg.spoke_overlay("ako_chat",
        extra_yaml={"retrieval_mode": "dense_only"})
"""

from core.ako_config.settings import (
    AKOConfig,
    ChunkConfig,
    HubPaths,
    ModelRouting,
    RetrievalConfig,
    SpokeConfig,
    get_config,
    reset_config,
)
from core.ako_config.paths import resolve_path, ensure_dir

__all__ = [
    "AKOConfig",
    "ChunkConfig",
    "HubPaths",
    "ModelRouting",
    "RetrievalConfig",
    "SpokeConfig",
    "get_config",
    "reset_config",
    "resolve_path",
    "ensure_dir",
]
