"""
AKO 统一配置 — 核心 Settings

读取优先级：
  1. 环境变量（最高）
  2. .env 文件（Hub 根目录下）
  3. hub.yaml（路径、模型等非敏感配置）
  4. 代码默认值（最低）
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 常量 ──────────────────────────────────────────────────────────

_HUB_YAML_CANDIDATES = [
    Path("D:/AKO/AKO_hub/config/hub.yaml"),
    Path("D:/AKO_Hub/config/hub.yaml"),
    Path("E:/AKO_Hub/config/hub.yaml"),
]

_ENV_CANDIDATES = [
    Path("D:/AKO/AKO_hub/.env"),
    Path("D:/AKO_Hub/.env"),
    Path("E:/AKO_Hub/.env"),
]

# 已知的 LLM 厂商 → 环境变量映射
_LLM_ENV_MAP = {
    "deepseek":  "DEEPSEEK_API_KEY",
    "kimi":      "KIMI_API_KEY",
    "minimax":   "MINIMAX_API_KEY",
    "aliyun":    "ALIYUN_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "openai":    "OPENAI_API_KEY",
}

# 已知的本地服务 → 环境变量映射
_SERVICE_ENV_MAP = {
    "ollama":    ("OLLAMA_HOST", "http://localhost:11434"),
    "sd":        ("SD_API_URL", "http://localhost:7860"),
    "comfyui":   ("COMFYUI_API_URL", "http://localhost:8188"),
    "chat":      ("CHAT_PORT", "7861"),
}


# ── 数据类 ────────────────────────────────────────────────────────

@dataclass
class HubPaths:
    """Hub 核心路径（从 hub.yaml 解析）"""
    sync_root: str = ""
    meta_db: str = ""
    chroma_root: str = ""
    file_root: str = ""
    backup_dir: str = ""
    log_dir: str = ""

    def resolve(self, relative: str) -> str:
        """将相对路径解析为基于 sync_root 的绝对路径"""
        if not relative:
            return ""
        p = Path(relative)
        if p.is_absolute():
            return str(p).replace("\\", "/")
        return str(Path(self.sync_root) / p).replace("\\", "/")


@dataclass
class ModelRouting:
    """LLM 模型分工路由"""
    reasoning: str = "openai"          # 结构计算、造价估算
    creative: str = "openai"            # 概念设计、风格分析
    vision: str = "aliyun"               # 图像理解 (qwen-vl)
    compliance: str = "openai"           # 规范校验
    embedding: str = "bge-m3"            # 统一嵌入模型 (Hub 锁定)
    fallback: str = "openai"           # 通用备用


@dataclass
class RetrievalConfig:
    """bge-m3 三向量混合检索参数"""
    mode: str = "hybrid"                 # hybrid | dense_only | sparse_only
    dense_weight: float = 0.33
    sparse_weight: float = 0.33
    colbert_weight: float = 0.34
    colbert_rerank_top_k: int = 20
    sparse_model: str = "bge-m3"
    dense_model: str = "bge-m3"

    @property
    def weights(self) -> Dict[str, float]:
        return {"dense": self.dense_weight, "sparse": self.sparse_weight, "colbert": self.colbert_weight}


@dataclass
class ChunkConfig:
    """文档分块参数"""
    size: int = 768
    overlap: int = 128
    min_size: int = 100


@dataclass
class SpokeConfig:
    """单个 Spoke 的配置覆盖层"""
    spoke_id: str = ""
    extra_env_vars: Dict[str, str] = field(default_factory=dict)
    output_dir: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# ── 主配置类 ──────────────────────────────────────────────────────

class AKOConfig:
    """
    AKO 全局统一配置。

    用法：
        cfg = get_config()
        cfg.hub_root
        cfg.api_key("deepseek")
        cfg.service_url("ollama")
    """

    def __init__(self, hub_yaml_path: Optional[str] = None, env_path: Optional[str] = None):
        # 1. 加载 .env（如存在）
        self._env_path = env_path or self._find_file(_ENV_CANDIDATES)
        if self._env_path:
            self._load_dotenv(self._env_path)

        # 2. 加载 hub.yaml
        self._yaml_path = hub_yaml_path or self._find_file(_HUB_YAML_CANDIDATES)
        raw = self._load_yaml(self._yaml_path)

        # 3. 解析路径
        self.paths = HubPaths(
            sync_root=raw.get("sync_root", ""),
            meta_db=self._abs(raw, "meta_db"),
            chroma_root=self._abs(raw, "chroma_root"),
            file_root=self._abs(raw, "file_root"),
            backup_dir=self._abs(raw, "backup_dir"),
            log_dir=self._abs(raw, "log_dir"),
        )

        # 4. 解析模型路由
        self.models = ModelRouting(
            embedding=raw.get("embedding_model", "bge-m3"),
        )

        # 5. 解析检索配置
        hybrid_w = raw.get("hybrid_weights", {})
        self.retrieval = RetrievalConfig(
            mode=raw.get("retrieval_mode", "hybrid"),
            dense_weight=hybrid_w.get("dense", 0.33),
            sparse_weight=hybrid_w.get("sparse", 0.33),
            colbert_weight=hybrid_w.get("colbert", 0.34),
            colbert_rerank_top_k=raw.get("colbert_rerank_top_k", 20),
            sparse_model=raw.get("sparse_model", "bge-m3"),
            dense_model=raw.get("dense_model", "bge-m3"),
        )

        # 6. 解析分块配置
        chunk_raw = raw.get("chunking", {})
        self.chunk = ChunkConfig(
            size=chunk_raw.get("size", 768),
            overlap=chunk_raw.get("overlap", 128),
            min_size=chunk_raw.get("min_size", 100),
        )

        # 7. 机器标识
        self.machine_id = raw.get("machine_id", "machine_01")
        self.peer_machine_id = raw.get("peer_machine_id", "machine_02")

        # 8. Spoke 源码映射
        self.spoke_sources: Dict[str, str] = raw.get("spoke_sources", {})

        # 9. 服务端口注册表
        ports_raw = raw.get("service_ports", {})
        self.service_ports = {
            "hub": ports_raw.get("hub", 7862),
            "chat": ports_raw.get("chat", 7861),
            "knowledge": ports_raw.get("knowledge", 8000),
            "sd": ports_raw.get("sd", 7860),
            "comfyui": ports_raw.get("comfyui", 8188),
            "ollama": ports_raw.get("ollama", 11434),
        }

        # 10. 知识库集合名称映射
        self.kb_collections: Dict[str, str] = raw.get("kb_collections", {})

        # 11. 保留原始 yaml 数据供扩展使用
        self._raw = raw

        # 12. 文件名规范
        self.filename_sep = raw.get("filename_sep", "_")
        self.version_prefix = raw.get("version_prefix", "v")

    # ── 快捷属性 ──────────────────────────────────────────────

    @property
    def hub_root(self) -> str:
        return self.paths.sync_root

    @property
    def chroma_root(self) -> str:
        return self.paths.chroma_root

    @property
    def meta_db(self) -> str:
        return self.paths.meta_db

    @property
    def file_root(self) -> str:
        return self.paths.file_root

    @property
    def embedding_model(self) -> str:
        return self.models.embedding

    @property
    def hub_url(self) -> str:
        """Hub API 基础地址"""
        port = self.service_ports.get("hub", 7862)
        return os.getenv("AKO_HUB_URL", f"http://127.0.0.1:{port}")

    # ── API Key 读取 ──────────────────────────────────────────

    def api_key(self, provider: str) -> str:
        """
        读取指定厂商的 API Key。

        Args:
            provider: 厂商名（deepseek / kimi / minimax / aliyun / dashscope / openai）

        Returns:
            API Key 字符串，未配置返回空字符串
        """
        env_var = _LLM_ENV_MAP.get(provider.lower(), f"{provider.upper()}_API_KEY")
        return os.getenv(env_var, "")

    def has_api_key(self, provider: str) -> bool:
        """检查指定厂商的 API Key 是否已配置"""
        return bool(self.api_key(provider))

    # ── 本地服务 URL ──────────────────────────────────────────

    def service_url(self, service: str) -> str:
        """
        读取本地服务 URL。优先环境变量，其次 hub.yaml service_ports。

        Args:
            service: 服务名（ollama / sd / comfyui / chat / hub / knowledge）

        Returns:
            URL 字符串
        """
        svc = _SERVICE_ENV_MAP.get(service.lower())
        if svc is not None:
            env_var, default = svc
            if service == "chat":
                port = os.getenv(env_var, str(self.service_ports.get("chat", default)))
                return f"http://localhost:{port}"
            return os.getenv(env_var, default)

        # 从 service_ports 回退
        port = self.service_ports.get(service.lower())
        if port:
            return f"http://localhost:{port}"
        return os.getenv(f"{service.upper()}_URL", "")

    # ── Spoke 辅助 ────────────────────────────────────────────

    def spoke_source_dir(self, spoke_id: str) -> str:
        """获取 Spoke 源码目录"""
        return self.spoke_sources.get(spoke_id, "")

    def spoke_overlay(
        self,
        spoke_id: str,
        extra_yaml: Optional[Dict[str, Any]] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> "AKOConfig":
        """
        创建 Spoke 专属配置覆盖层。返回新 AKOConfig 实例，叠加 spoke 级配置。

        典型用法:
            cfg = get_config()
            spoke_cfg = cfg.spoke_overlay("ako_chat",
                extra_yaml={"retrieval_mode": "dense_only"},
                extra_env={"CHAT_PORT": "17861"})

        Args:
            spoke_id: Spoke 标识
            extra_yaml: 覆盖的 yaml 配置键值对
            extra_env: 额外环境变量
        """
        merged_raw = dict(self._raw)
        if extra_yaml:
            merged_raw.update(extra_yaml)

        overlay = AKOConfig.__new__(AKOConfig)
        overlay._yaml_path = self._yaml_path
        overlay._env_path = self._env_path

        # 路径继承
        overlay.paths = self.paths

        # 模型继承
        overlay.models = ModelRouting(
            embedding=merged_raw.get("embedding_model", self.models.embedding),
            reasoning=self.models.reasoning,
            creative=self.models.creative,
            vision=self.models.vision,
            compliance=self.models.compliance,
            fallback=self.models.fallback,
        )

        # 检索配置覆盖
        hybrid_w = merged_raw.get("hybrid_weights", self.retrieval.weights)
        overlay.retrieval = RetrievalConfig(
            mode=merged_raw.get("retrieval_mode", self.retrieval.mode),
            dense_weight=hybrid_w.get("dense", self.retrieval.dense_weight),
            sparse_weight=hybrid_w.get("sparse", self.retrieval.sparse_weight),
            colbert_weight=hybrid_w.get("colbert", self.retrieval.colbert_weight),
            colbert_rerank_top_k=merged_raw.get(
                "colbert_rerank_top_k", self.retrieval.colbert_rerank_top_k
            ),
            sparse_model=merged_raw.get("sparse_model", self.retrieval.sparse_model),
            dense_model=merged_raw.get("dense_model", self.retrieval.dense_model),
        )

        # 分块配置覆盖
        chunk_raw = merged_raw.get("chunking", {})
        overlay.chunk = ChunkConfig(
            size=chunk_raw.get("size", self.chunk.size),
            overlap=chunk_raw.get("overlap", self.chunk.overlap),
            min_size=chunk_raw.get("min_size", self.chunk.min_size),
        )

        overlay.machine_id = self.machine_id
        overlay.peer_machine_id = self.peer_machine_id
        overlay.spoke_sources = self.spoke_sources
        overlay.service_ports = dict(self.service_ports)
        overlay.kb_collections = dict(self.kb_collections)
        overlay.filename_sep = self.filename_sep
        overlay.version_prefix = self.version_prefix
        overlay._raw = merged_raw

        # 环境变量覆盖
        if extra_env:
            for k, v in extra_env.items():
                os.environ[k] = v

        return overlay

    def get(self, key: str, default: Any = None) -> Any:
        """读取 hub.yaml 中的任意键"""
        return self._raw.get(key, default)

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _find_file(candidates: List[Path]) -> Optional[str]:
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    @staticmethod
    def _load_yaml(path: Optional[str]) -> Dict[str, Any]:
        if not path:
            return {}
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            print(f"[ako_config] ⚠️ PyYAML 未安装，无法加载 {path}")
            return {}
        except Exception as e:
            print(f"[ako_config] ⚠️ 加载 hub.yaml 失败: {e}")
            return {}

    @staticmethod
    def _load_dotenv(path: str) -> None:
        """
        轻量 .env 加载器（无 python-dotenv 依赖）。
        仅支持 KEY=VALUE 格式，忽略注释和空行。
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("\"'")
                        # 不覆盖已有环境变量
                        if key and key not in os.environ:
                            os.environ[key] = value
        except Exception as e:
            print(f"[ako_config] ⚠️ 加载 .env 失败: {e}")

    def _abs(self, raw: Dict, key: str) -> str:
        """将 yaml 中的路径解析为绝对路径"""
        value = raw.get(key, "")
        if not value:
            return ""
        p = Path(value)
        if p.is_absolute():
            return str(p).replace("\\", "/")
        root = raw.get("sync_root", "")
        if root:
            return str(Path(root) / p).replace("\\", "/")
        return str(p).replace("\\", "/")

    def __repr__(self) -> str:
        return (
            f"AKOConfig(hub_root={self.hub_root!r}, "
            f"embedding={self.embedding_model!r}, "
            f"retrieval={self.retrieval.mode}, "
            f"machine={self.machine_id!r})"
        )


# ── 全局单例 ──────────────────────────────────────────────────────

_instance: Optional[AKOConfig] = None


def get_config(hub_yaml_path: Optional[str] = None, env_path: Optional[str] = None) -> AKOConfig:
    """获取全局配置单例。首次调用时加载，后续复用。"""
    global _instance
    if _instance is None:
        _instance = AKOConfig(hub_yaml_path=hub_yaml_path, env_path=env_path)
    return _instance


def reset_config() -> None:
    """重置单例（用于测试或热重载）。"""
    global _instance
    _instance = None
