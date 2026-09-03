"""
registry/taxonomy.py — AKO Hub Agent 分类学（单一数据源）。

定义 AKO Hub 中所有 Spoke（Agent/Workflow）的三维分类：

    ① domain（业务域）    —— 解决什么领域问题
    ② function（功能类型）—— 在链路中扮演什么角色
    ③ lifecycle（生命周期）—— 当前阶段

本模块是分类的唯一权威来源（Single Source of Truth）。
registry/workflows.py、HTTP 注册表、Agent Card、意图路由均从此派生，
避免各处各写一套导致「未分类」无法被机器发现。

文档编号: AGE-TECH-AKO-HUB-001 §6.3（分类学扩展）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set


# ── 三维枚举 ───────────────────────────────────────────────────────

# ① 业务域（domain）
#    architecture（设计）与 engineering（图纸/质检）已合并为一个工程 domain。
DOMAIN_ENGINEERING = "engineering"      # 工程：结构设计 + 图纸质检 + 图像分析 + 工程工作流
DOMAIN_CONTENT = "content"              # 内容：营销/GEO/媒体/排版
DOMAIN_COMMERCE = "commerce"            # 商业：商业作战/报价
DOMAIN_DATA = "data"                    # 数据：表单/知识库/报表
DOMAIN_OPS = "ops"                      # 运维：网络监控/健康巡检
DOMAIN_GOVERNANCE = "governance"        # 治理：法律/审计/合规
DOMAIN_INFRASTRUCTURE = "infrastructure"  # 基础设施：Hub 总线自身

VALID_DOMAINS: Set[str] = {
    DOMAIN_ENGINEERING,
    DOMAIN_CONTENT,
    DOMAIN_COMMERCE,
    DOMAIN_DATA,
    DOMAIN_OPS,
    DOMAIN_GOVERNANCE,
    DOMAIN_INFRASTRUCTURE,
}

# ② 功能类型（function）
FUNCTION_PRODUCER = "producer"          # 产出物生成：报价/报表/排版/推文/方案
FUNCTION_ANALYZER = "analyzer"          # 分析判定：图像分析/审图/法律审查/审计
FUNCTION_RETRIEVER = "retriever"        # 检索问答：知识库/chat/RAG
FUNCTION_INGESTOR = "ingestor"          # 数据采集：表单提取/SFTP 拉取
FUNCTION_MONITOR = "monitor"            # 监控巡检：网络监控/心跳/审计（定时）
FUNCTION_ORCHESTRATOR = "orchestrator"  # 编排中枢：Hub/工作流

VALID_FUNCTIONS: Set[str] = {
    FUNCTION_PRODUCER,
    FUNCTION_ANALYZER,
    FUNCTION_RETRIEVER,
    FUNCTION_INGESTOR,
    FUNCTION_MONITOR,
    FUNCTION_ORCHESTRATOR,
}

# ③ 生命周期（lifecycle）
VALID_LIFECYCLES: Set[str] = {
    "registered",
    "active",
    "deprecated",
    "staging",
}

# 未分类占位值（显式标记，确保「未分类」可被发现）
UNCLASSIFIED = ""


# ── 权威映射：workflow_id → (domain, function) ────────────────────

# 与 registry/workflows.py 的 SPOKE_REGISTRY 严格对齐。
# 所有条目必须在此登记，否则会被 find_unclassified() 报告为「未分类」。
TAXONOMY: Dict[str, Dict[str, str]] = {
    # ── 基础设施 ──────────────────────────────────────────────
    "AKO_hub": {
        "domain": DOMAIN_INFRASTRUCTURE,
        "function": FUNCTION_ORCHESTRATOR,
    },
    # intake：工厂唯一大门（人机入口/工单生成投递），与 hub 同属基础设施编排域
    "AKO_hub_intake_agent": {
        "domain": DOMAIN_INFRASTRUCTURE,
        "function": FUNCTION_ORCHESTRATOR,
    },
    # ── 批2 L0 注册级（2026-09-03）：GUI/工具型，仅看板可见，禁止 hub 调度 ──
    "AKO_chart_agent": {"domain": DOMAIN_DATA, "function": FUNCTION_PRODUCER},
    "AKO_art_agent": {"domain": DOMAIN_CONTENT, "function": FUNCTION_ANALYZER},
    "AKO_web_consult_agent": {"domain": DOMAIN_CONTENT, "function": FUNCTION_RETRIEVER},
    "AKO_git_push_agent": {"domain": DOMAIN_OPS, "function": FUNCTION_INGESTOR},
    "AKO_pack_agent": {"domain": DOMAIN_OPS, "function": FUNCTION_PRODUCER},
    "AKO_pipeline_agent": {"domain": DOMAIN_INFRASTRUCTURE, "function": FUNCTION_ORCHESTRATOR},
    "AKO_file_tag_manager": {"domain": DOMAIN_DATA, "function": FUNCTION_INGESTOR},
    "AKO_review_runner_agent": {"domain": DOMAIN_OPS, "function": FUNCTION_ANALYZER},
    # ── 工程域（设计 + 图纸/质检 + 图像分析 + 工程工作流） ─────
    "AKO_architect_agent": {
        "domain": DOMAIN_ENGINEERING,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_drawing_inspector": {
        "domain": DOMAIN_ENGINEERING,
        "function": FUNCTION_ANALYZER,
    },
    "AKO_image_analyzer_agent": {
        "domain": DOMAIN_ENGINEERING,
        "function": FUNCTION_ANALYZER,
    },
    "AKO_workflow": {
        "domain": DOMAIN_ENGINEERING,
        "function": FUNCTION_ORCHESTRATOR,
    },
    # ── 内容域 ────────────────────────────────────────────────
    "AKO_geo": {
        "domain": DOMAIN_CONTENT,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_media_agent": {
        "domain": DOMAIN_CONTENT,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_layout_agent": {
        "domain": DOMAIN_CONTENT,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_writer_agent": {
        "domain": DOMAIN_CONTENT,
        "function": FUNCTION_PRODUCER,
    },
    # ── 商业域 ────────────────────────────────────────────────
    "AKO_business_agent": {
        "domain": DOMAIN_COMMERCE,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_quote_agent": {
        "domain": DOMAIN_COMMERCE,
        "function": FUNCTION_PRODUCER,
    },
    # ── 数据域 ────────────────────────────────────────────────
    "AKO_chat": {
        "domain": DOMAIN_DATA,
        "function": FUNCTION_RETRIEVER,
    },
    "AKO_reports": {
        "domain": DOMAIN_DATA,
        "function": FUNCTION_PRODUCER,
    },
    "AKO_form_extractor": {
        "domain": DOMAIN_DATA,
        "function": FUNCTION_INGESTOR,
    },
    "AKO_knowledge": {
        "domain": DOMAIN_DATA,
        "function": FUNCTION_RETRIEVER,
    },
    # ── 运维域 ────────────────────────────────────────────────
    "AKO_netwatch_agent": {
        "domain": DOMAIN_OPS,
        "function": FUNCTION_MONITOR,
    },
    # ── 治理域 ────────────────────────────────────────────────
    "AKO_law_agent": {
        "domain": DOMAIN_GOVERNANCE,
        "function": FUNCTION_ANALYZER,
    },
    "AKO_audit_agent": {
        "domain": DOMAIN_GOVERNANCE,
        "function": FUNCTION_MONITOR,
    },
}


# ── 查询辅助 ───────────────────────────────────────────────────────

def get_domain(workflow_id: str) -> str:
    """返回某个 workflow 的业务域；未登记返回 UNCLASSIFIED。"""
    return TAXONOMY.get(workflow_id, {}).get("domain", UNCLASSIFIED)


def get_function(workflow_id: str) -> str:
    """返回某个 workflow 的功能类型；未登记返回 UNCLASSIFIED。"""
    return TAXONOMY.get(workflow_id, {}).get("function", UNCLASSIFIED)


def get_category(workflow_id: str) -> str:
    """
    返回复合分类字符串，格式: "{domain}/{function}"。
    用于对齐 HTTP 注册表的 card.category。
    未分类时返回 UNCLASSIFIED。
    """
    domain = get_domain(workflow_id)
    function = get_function(workflow_id)
    if not domain or not function:
        return UNCLASSIFIED
    return f"{domain}/{function}"


def list_by_domain(domain: str) -> List[str]:
    """列出属于某业务域的全部 workflow_id。"""
    return [wid for wid, t in TAXONOMY.items() if t.get("domain") == domain]


def list_by_function(function: str) -> List[str]:
    """列出属于某功能类型的全部 workflow_id。"""
    return [wid for wid, t in TAXONOMY.items() if t.get("function") == function]


def is_valid_domain(domain: str) -> bool:
    return domain in VALID_DOMAINS


def is_valid_function(function: str) -> bool:
    return function in VALID_FUNCTIONS


def find_unclassified(registered_ids: Optional[List[str]] = None) -> List[str]:
    """
    找出「未分类」的 workflow。

    若传入 registered_ids（如 SPOKE_REGISTRY 全部 workflow_id），
    则额外报告「已注册但未在 TAXONOMY 登记」的条目；
    否则仅报告 TAXONOMY 中 domain/function 缺失的条目。

    返回未分类的 workflow_id 列表。
    """
    unclassified: List[str] = []

    # 1) 已登记但维度缺失
    for wid, t in TAXONOMY.items():
        if not t.get("domain") or not t.get("function"):
            unclassified.append(wid)

    # 2) 已注册但未登记
    if registered_ids is not None:
        known = set(TAXONOMY.keys())
        for wid in registered_ids:
            if wid not in known:
                unclassified.append(wid)

    # 去重并保持稳定顺序
    seen: Set[str] = set()
    result = []
    for wid in unclassified:
        if wid not in seen:
            seen.add(wid)
            result.append(wid)
    return result


def set_classification(workflow_id: str, domain: str, function: str) -> bool:
    """
    登记/更新某个 workflow 的 domain/function 分类映射。

    非法值（domain/function 不在枚举内）返回 False 且不写入；
    合法时写入 TAXONOMY 并返回 True。幂等：重复登记同值返回 True。
    """
    if not workflow_id or not is_valid_domain(domain) or not is_valid_function(function):
        return False
    TAXONOMY[workflow_id] = {"domain": domain, "function": function}
    return True