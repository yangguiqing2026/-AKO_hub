"""
AKO Hub — ako_geo 配置常量
config.py: GEO Spoke 全局配置，包含路径、平台列表、LLM 路由等。

文档编号: AGE-TECH-AKO-GEO-001 §1
"""

from pathlib import Path

# ── 根目录 ──────────────────────────────────────────────────────────
AKO_HUB_ROOT = Path(__file__).resolve().parent.parent

# GEO 输出根目录（不在百度网盘同步目录下）
GEO_OUTPUT_ROOT = AKO_HUB_ROOT / "geo_output"

# 模板目录
TEMPLATES_DIR = GEO_OUTPUT_ROOT / "templates"

# Obsidian 笔记输出目录
OBSIDIAN_DIR = GEO_OUTPUT_ROOT / "obsidian"

# 审核失败/生成失败目录
FAILED_DIR = GEO_OUTPUT_ROOT / "failed"

# 效果监测目录
MONITOR_DIR = GEO_OUTPUT_ROOT / "monitor"

# GEO 配置目录
GEO_CONFIG_DIR = AKO_HUB_ROOT / "geo_config"

# 合法标签白名单
HUB_GEO_TAGS_FILE = GEO_CONFIG_DIR / "hub_geo_tags.json"

# 日志目录
LOG_DIR = AKO_HUB_ROOT / "logs"

# ── 平台配置 ────────────────────────────────────────────────────────
PLATFORMS = ["zhihu", "wechat", "douyin", "baijia"]

# 平台对应文件扩展名
PLATFORM_EXT = {
    "zhihu": "md",
    "wechat": "md",
    "douyin": "txt",
    "baijia": "md",
}

# ── LangGraph 状态机配置 ────────────────────────────────────────────
MAX_REVIEW_LOOP = 3          # 审核驳回最大循环次数
SCAN_INTERVAL_SECONDS = 900  # N0_Scan 扫描间隔（15 分钟）

# ── LLM 路由配置 ────────────────────────────────────────────────────
# N3_Outline: 深度构思，优先 deepseek
LLM_ROUTE_OUTLINE = {
    "primary": "openai",
    "fallback": ["kimi", "ollama"],
}

# N5_Format: 长文润色用 kimi，短文案/标题用 qwen
LLM_ROUTE_FORMAT_LONG = {
    "primary": "openai",
    "fallback": ["deepseek", "ollama"],
}
LLM_ROUTE_FORMAT_SHORT = {
    "primary": "openai",
    "fallback": ["kimi", "ollama"],
}

# LLM 生成额度（max_tokens）：Qwen3 是思考模型，推理会占用 token 额度，
# 需给足以避免正文被挤占而返回空 content。该值须小于 llama.cpp 的 --ctx-size。
LLM_MAX_TOKENS = 4096

# ── KnowledgeHub 配置 ───────────────────────────────────────────────
# GEO 锚点专用 Collection（优先检索）
GEO_ANCHORS_COLLECTION = "hub_geo_anchors"

# 降级通用文档索引
GEO_DEFAULT_COLLECTION = "default"

# 检索参数
GEO_QUERY_TOP_K = 5
GEO_FALLBACK_TOP_K = 3

# ── 扫描路径模式 ────────────────────────────────────────────────────
# 各业务 Agent 的 geo.yaml 放置路径模式
# 实际路径: D:\AKO_Hub\{agent_name}\output\{task_id}\geo.yaml
GEO_YAML_GLOB_PATTERN = "*/output/*/geo.yaml"

# ── 合法 agent 枚举 ─────────────────────────────────────────────────
VALID_AGENTS = [
    "architect_agent",
    "business_agent",
    "workflow",
    "image_analyzer",
    "chat",
    "knowledge",
]

# ── 敏感度枚举 ──────────────────────────────────────────────────────
SENSITIVITY_LEVELS = ["P0", "P1", "P2"]
