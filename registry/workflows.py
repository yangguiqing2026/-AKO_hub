"""
AKO Hub — Spoke 注册表
Workflows: 现有 Agent 与 Workflow 的注册信息。

文档编号: AGE-TECH-AKO-HUB-001 §6.3
"""

from typing import TypedDict, List, Optional, Dict, Any

from .taxonomy import (
    get_domain,
    get_function,
    get_category,
    find_unclassified,
)


class SpokeInfo(TypedDict):
    """Spoke（Agent 或 Workflow）的注册信息。"""
    workflow_id: str
    name: str
    spoke_type: str                       # "agent" | "workflow" | "subgraph"
    entry_module: str                     # Python 模块入口，如 "agents.ako_architect"
    entry_function: Optional[str]         # 入口函数，如 "run"；若为 LangGraph 子图则留空
    required_kb_ids: List[str]           # 默认挂载的知识库
    output_dir: str                       # 默认输出目录（相对于 files/）
    description: str
    status: str                           # "registered" | "active" | "deprecated"
    source_dir: str                       # Spoke 项目源码绝对路径
    invoke_mode: str                      # "importlib" (默认) | "subprocess"


# ── 现有资产注册表（与用户实际资产严格对齐） ─────────────────────────
# 资产清单：
#   - Agent:  AKO_architect_agent × 1
#   - Agent:  AKO_drawing_inspector × 3（01/02/03，可按实际命名替换）
#   - Agent:  AKO_image_analyzer × 3（01/02/03，可按实际命名替换）
#   - Workflow: AKO_workflow × 1
# 合计：7 个 Agent + 1 个 Workflow

SPOKE_REGISTRY: List[SpokeInfo] = [
    # ── AKO_hub（总线调度中枢） ──────────────────────────────
    {
        "workflow_id": "AKO_hub",
        "name": "AKO_hub（总线调度 Agent）",
        "spoke_type": "agent",
        "entry_module": "src.core.main",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "总线调度中枢：Agent 注册、意图路由、工作流编排、健康巡检",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub",
        "invoke_mode": "importlib",
    },
    # ── AKO_hub_intake_agent（工厂大门） ─────────────────────────
    {
        "workflow_id": "AKO_hub_intake_agent",
        "name": "AKO_hub_intake_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_intake_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_taoli_general_arch"],
        "output_dir": "intake_output",
        "description": "工厂唯一大门：自然语言→ako1 工单，P0 歧义消解 + M07 独立评审后投递",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub_intake_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_architect_agent（1 个） ─────────────────────────────
    {
        "workflow_id": "AKO_architect_agent",
        "name": "AKO_architect_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_architect_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_knowledge_base", "ako_tech_struct"],
        "output_dir": "taoli_wallboard/tech_docs",
        "description": "建筑结构设计：结构计算、方案设计、技术文档生成",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_architect_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_drawing_inspector（1 个） ───────────────────────────
    {
        "workflow_id": "AKO_drawing_inspector",
        "name": "AKO_drawing_inspector",
        "spoke_type": "agent",
        "entry_module": "agents.ako_drawing_inspector",
        "entry_function": "run",
        "required_kb_ids": ["ako_knowledge_base", "ako_drawing_qc"],
        "output_dir": "taoli_wallboard/drawings/qc",
        "description": "图纸质检 Agent：图纸规范检查、标注审查",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_drawing_inspector_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_image_analyzer（1 个） ─────────────────────────────
    {
        "workflow_id": "AKO_image_analyzer_agent",
        "name": "AKO_image_analyzer_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_image_analyzer",
        "entry_function": "run",
        "required_kb_ids": ["ako_knowledge_base", "ako_image_corpus"],
        "output_dir": "taoli_wallboard/reports/analyzer",
        "description": "图像分析 Agent：施工现场图像分析、缺陷识别",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_image_analyzer_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO 主工作流（1 个） ──────────────────────────────────
    # 2026-09-03 §九 清扫：id 由中文 'AKO工作流' 统一为英文 AKO_workflow
    # （历史沿用 D:\AKO工作流 中文目录名；目录与 adapter 不改，仅注册面规范化）
    {
        "workflow_id": "AKO_workflow",
        "name": "AKO_workflow",
        "spoke_type": "workflow",
        "entry_module": "agents.ako_workflow_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_taoli_general_arch", "ako_taoli_building_codes_arch"],
        "output_dir": "taoli_wallboard/workflow_outputs",
        "description": "陶粒墙板智能工作流：配比优化、技术方案、商业分析、质检、可行性研究",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub",
        "invoke_mode": "importlib",
    },
    # ── AKO_chat（RAG 知识库对话） ─────────────────────────────
    {
        "workflow_id": "AKO_chat",
        "name": "AKO_chat",
        "spoke_type": "agent",
        "entry_module": "agents.ako_chat_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_taoli_general_arch"],
        "output_dir": "taoli_wallboard/chat_logs",
        "description": "RAG 知识库对话：建筑规范问答、专业知识检索、引用溯源",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub",
        "invoke_mode": "importlib",
    },
    # ── AKO_geo（内容营销×GEO×知识发酵） ─────────────────────────
    {
        "workflow_id": "AKO_geo",
        "name": "AKO_geo",
        "spoke_type": "workflow",
        "entry_module": "ako_geo.spoke",
        "entry_function": "run",
        "required_kb_ids": ["hub_geo_anchors", "ako_taoli_general_arch"],
        "output_dir": "geo_output",
        "description": "内容营销×GEO×知识发酵：将业务成果外化为多平台营销内容，AI搜索优化与知识发酵",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub/ako_geo",
        "invoke_mode": "importlib",
    },
    # ── AKO_reports（报表模版生成） ────────────────────────────
    {
        "workflow_id": "AKO_reports",
        "name": "AKO_reports",
        "spoke_type": "agent",
        "entry_module": "agents.ako_reports_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "reports_output",
        "description": "报表生成：根据 JSON 配置 + 图片数据，Jinja2 渲染生成自包含 HTML 报告",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub",
        "invoke_mode": "subprocess",
    },
    # ── AKO_business（商业作战指挥） ─────────────────────────────
    {
        "workflow_id": "AKO_business_agent",
        "name": "AKO_business_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_business_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "business_output",
        "description": "商业作战指挥：报价单生成、风险评估、每日简报",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_business_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_quote（装配式建筑报价引擎） ─────────────────────────
    {
        "workflow_id": "AKO_quote_agent",
        "name": "AKO_quote_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_quote_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "quote_output",
        "description": "装配式建筑报价引擎：墙板/箱体成本计算、税金汇总",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_quote_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_media（内容营销流水线） ─────────────────────────────
    {
        "workflow_id": "AKO_media_agent",
        "name": "AKO_media_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_media_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "media_output",
        "description": "内容营销5层流水线：采集→分析→决策→发布→反馈→进化",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_media_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_layout_agent（智能排版） ──────────────────────────
    {
        "workflow_id": "AKO_layout_agent",
        "name": "AKO_layout_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_layout_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "layout_output",
        "description": "智能排版：效果图/平面图自动排版为商业签单图册，输出 PDF/PPTX/JPG",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_layout_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_form_extractor（表单数据提取） ────────────────────
    {
        "workflow_id": "AKO_form_extractor",
        "name": "AKO_form_extractor",
        "spoke_type": "agent",
        "entry_module": "agents.ako_form_extractor_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "form_extractor_output",
        "description": "表单提取：微信小程序表单数据 SFTP 拉取 → 本地解析入库",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_hub",
        "invoke_mode": "importlib",
    },
    # ── AKO_netwatch_agent（网络监控） ────────────────────────
    {
        "workflow_id": "AKO_netwatch_agent",
        "name": "AKO_netwatch_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_netwatch_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "netwatch_output",
        "description": "网络监控：HTTP/SSL/域名/ICP 全量检查 + SFTP 备份管理",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_netwatch_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_knowledge（知识库服务） ───────────────────────────
    {
        "workflow_id": "AKO_knowledge",
        "name": "AKO_knowledge",
        "spoke_type": "agent",
        "entry_module": "agents.ako_knowledge_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "knowledge_output",
        "description": "知识库：bge-m3 三向量混合检索 + ChromaDB + FastAPI 服务",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_knowledge",
        "invoke_mode": "importlib",
    },
    # ── AKO_law_agent（法律审查与合规校验） ──────────────────
    {
        "workflow_id": "AKO_law_agent",
        "name": "AKO_law_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_law_adapter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "law_output",
        "description": "法律审查与合规校验：六维度评分卡 + legal_self_check，Vault 立法文件合规审查",
        "status": "active",
        "source_dir": "D:/AKO/AKO_law_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO_writer_agent（技术写作） ─────────────────────────────
    {
        "workflow_id": "AKO_writer_agent",
        "name": "AKO_writer_agent",
        "spoke_type": "agent",
        "entry_module": "agents.ako_writer_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_taoli_general_arch"],
        "output_dir": "writer_output",
        "description": "技术写作：N0 选题 → N1 检索 → N2 大纲（人工确认闭环）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_writer_agent",
        "invoke_mode": "importlib",
    },
    # ── 批2 工具/GUI 型（L0 注册级，invoke_mode=manual_gui：看板可见、禁止 hub 调度）─
    # 2026-09-03 口径：chart/art/web_consult=GUI 人工；git_push/pack/pipeline/
    # file_tag_manager/review_runner=内部工具，均不做 NL 路由（task_router 护栏拒绝显式调度）
    {
        "workflow_id": "AKO_chart_agent",
        "name": "AKO_chart_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "图表生成（GUI 人工型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_chart_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_art_agent",
        "name": "AKO_art_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "美术评估（GUI 人工型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_art_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_web_consult_agent",
        "name": "AKO_web_consult_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "网站咨询（GUI 人工型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_web_consult_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_git_push_agent",
        "name": "AKO_git_push_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "Git 推送（内部工具型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_git_push_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_pack_agent",
        "name": "AKO_pack_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "安装包构建（内部工具型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_pack_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_pipeline_agent",
        "name": "AKO_pipeline_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "流水线编排（内部工具型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_pipeline_agent",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_file_tag_manager",
        "name": "AKO_file_tag_manager",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "文件标签管理（内部工具型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_file_tag_manager",
        "invoke_mode": "manual_gui",
    },
    {
        "workflow_id": "AKO_review_runner_agent",
        "name": "AKO_review_runner_agent",
        "spoke_type": "agent",
        "entry_module": "",
        "entry_function": "",
        "required_kb_ids": [],
        "output_dir": "",
        "description": "代码审查（内部工具型，L0 注册，2026-09-03 批2）",
        "status": "registered",
        "source_dir": "D:/AKO/AKO_review_runner",
        "invoke_mode": "manual_gui",
    },

]


# ── 查询辅助 ───────────────────────────────────────────────────

def get_spoke_by_id(workflow_id: str) -> Optional[SpokeInfo]:
    for s in SPOKE_REGISTRY:
        if s["workflow_id"] == workflow_id:
            return s
    return None


def list_spokes_by_type(spoke_type: str) -> List[SpokeInfo]:
    return [s for s in SPOKE_REGISTRY if s["spoke_type"] == spoke_type]


def list_all_spokes() -> List[SpokeInfo]:
    return list(SPOKE_REGISTRY)


# ── 动态注册（供 hub_api.py 调用） ──────────────────────────────

def register_spoke(spoke_info: SpokeInfo) -> bool:
    """
    注册或更新一个 Spoke。

    Returns:
        True 表示新增，False 表示更新了已有记录。
    """
    global SPOKE_REGISTRY
    workflow_id = spoke_info["workflow_id"]

    # 查找是否已存在
    for i, existing in enumerate(SPOKE_REGISTRY):
        if existing["workflow_id"] == workflow_id:
            SPOKE_REGISTRY[i] = spoke_info
            return False  # 更新

    # 新增
    SPOKE_REGISTRY.append(spoke_info)
    return True


def unregister_spoke(workflow_id: str) -> bool:
    """
    移除一个已注册的 Spoke。

    Returns:
        True 表示成功移除，False 表示未找到。
    """
    global SPOKE_REGISTRY
    for i, spoke in enumerate(SPOKE_REGISTRY):
        if spoke["workflow_id"] == workflow_id:
            SPOKE_REGISTRY.pop(i)
            return True
    return False


def get_spokes_by_source_dir(source_dir: str) -> List[SpokeInfo]:
    """根据源码目录查找 Spoke（用于动态发现）。"""
    normalized = source_dir.replace("\\", "/").rstrip("/")
    return [
        s for s in SPOKE_REGISTRY
        if s.get("source_dir", "").replace("\\", "/").rstrip("/") == normalized
    ]


# ── 分类学派生（单一数据源：registry/taxonomy.py） ─────────────

def enrich_spoke(spoke: SpokeInfo) -> Dict[str, Any]:
    """
    在 Spoke 注册信息上附加三维分类字段。

    返回包含 domain / function / category 的字典。
    分类值统一来自 registry/taxonomy.py，不在注册表内重复维护。
    """
    wid = spoke["workflow_id"]
    enriched = dict(spoke)
    enriched["domain"] = get_domain(wid)
    enriched["function"] = get_function(wid)
    enriched["category"] = get_category(wid)
    return enriched


def list_spokes_enriched() -> List[Dict[str, Any]]:
    """返回全部 Spoke 的富化信息（含 domain / function / category）。"""
    return [enrich_spoke(s) for s in SPOKE_REGISTRY]


def list_unclassified() -> List[str]:
    """
    返回「未分类」的 workflow_id 列表。

    覆盖两类情况：
      1. 已注册但未在 taxonomy 登记；
      2. 在 taxonomy 登记但 domain/function 缺失。
    """
    registered_ids = [s["workflow_id"] for s in SPOKE_REGISTRY]
    return find_unclassified(registered_ids)
