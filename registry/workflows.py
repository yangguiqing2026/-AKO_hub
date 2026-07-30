"""
AKO Hub — Spoke 注册表
Workflows: 现有 Agent 与 Workflow 的注册信息。

文档编号: AGE-TECH-AKO-HUB-001 §6.3
"""

from typing import TypedDict, List, Optional


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
        "source_dir": "E:/AKO_hub",
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
        "source_dir": "D:/AKO_architect_agent",
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
        "source_dir": "D:/AKO_drawing_inspector",
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
        "source_dir": "E:/AKO_image_analyzer_agent",
        "invoke_mode": "importlib",
    },
    # ── AKO 主工作流（1 个） ──────────────────────────────────
    {
        "workflow_id": "AKO工作流",
        "name": "AKO工作流",
        "spoke_type": "workflow",
        "entry_module": "agents.ako_workflow_adapter",
        "entry_function": "run",
        "required_kb_ids": ["ako_taoli_general_arch", "ako_taoli_building_codes_arch"],
        "output_dir": "taoli_wallboard/workflow_outputs",
        "description": "陶粒墙板智能工作流：配比优化、技术方案、商业分析、质检、可行性研究",
        "status": "registered",
        "source_dir": "D:/AKO工作流",
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
        "source_dir": "D:/AKO_chat",
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
        "source_dir": "D:/AKO_Hub/ako_geo",
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
        "source_dir": "D:/AKO_Report_Template-v1.0",
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
        "source_dir": "D:/AKO_business_agent",
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
        "source_dir": "D:/AKO_quote_agent",
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
        "source_dir": "D:/AKO_media_agent",
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
        "source_dir": "D:/AKO_layout_agent",
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
        "source_dir": "D:/AKO_form_extractor",
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
        "source_dir": "D:/AKO_netwatch_agent",
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
        "source_dir": "D:/AKO_knowledge",
        "invoke_mode": "importlib",
    },
    # ── AKO_code_compliance（规范合规校验） ────────────────────
    {
        "workflow_id": "AKO_code_compliance",
        "name": "AKO_code_compliance",
        "spoke_type": "agent",
        "entry_module": "agents.ako_code_compliance",
        "entry_function": "run",
        "required_kb_ids": ["ako_building_codes"],
        "output_dir": "compliance_output",
        "description": "规范合规校验：自动比对国标/地标，输出合规报告与整改建议",
        "status": "registered",
        "source_dir": "D:/AKO_code_compliance",
        "invoke_mode": "importlib",
    },
    # ── AKO_material_selector（材料选型） ─────────────────────
    {
        "workflow_id": "AKO_material_selector",
        "name": "AKO_material_selector",
        "spoke_type": "agent",
        "entry_module": "agents.ako_material_selector",
        "entry_function": "run",
        "required_kb_ids": ["ako_material_db"],
        "output_dir": "material_output",
        "description": "材料选型：根据性能指标与成本约束，推荐最优建材方案",
        "status": "registered",
        "source_dir": "D:/AKO_material_selector",
        "invoke_mode": "importlib",
    },
    # ── AKO_energy_analyzer（能耗分析） ───────────────────────
    {
        "workflow_id": "AKO_energy_analyzer",
        "name": "AKO_energy_analyzer",
        "spoke_type": "agent",
        "entry_module": "agents.ako_energy_analyzer",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "energy_output",
        "description": "能耗分析：建筑热工模拟、节能优化建议、绿建评分",
        "status": "registered",
        "source_dir": "D:/AKO_energy_analyzer",
        "invoke_mode": "importlib",
    },
    # ── AKO_fire_safety（消防设计） ──────────────────────────
    {
        "workflow_id": "AKO_fire_safety",
        "name": "AKO_fire_safety",
        "spoke_type": "agent",
        "entry_module": "agents.ako_fire_safety",
        "entry_function": "run",
        "required_kb_ids": ["ako_fire_codes"],
        "output_dir": "fire_safety_output",
        "description": "消防设计：疏散计算、防火分区、消防设施布置",
        "status": "registered",
        "source_dir": "D:/AKO_fire_safety",
        "invoke_mode": "importlib",
    },
    # ── AKO_accessibility（无障碍设计） ───────────────────────
    {
        "workflow_id": "AKO_accessibility",
        "name": "AKO_accessibility",
        "spoke_type": "agent",
        "entry_module": "agents.ako_accessibility",
        "entry_function": "run",
        "required_kb_ids": ["ako_accessibility_codes"],
        "output_dir": "accessibility_output",
        "description": "无障碍设计：坡道/电梯/卫生间无障碍合规校验与方案生成",
        "status": "registered",
        "source_dir": "D:/AKO_accessibility",
        "invoke_mode": "importlib",
    },
    # ── AKO_site_planner（场地规划） ─────────────────────────
    {
        "workflow_id": "AKO_site_planner",
        "name": "AKO_site_planner",
        "spoke_type": "agent",
        "entry_module": "agents.ako_site_planner",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "site_output",
        "description": "场地规划：用地分析、建筑退距、日照计算、总图排版",
        "status": "registered",
        "source_dir": "D:/AKO_site_planner",
        "invoke_mode": "importlib",
    },
    # ── AKO_mep_engineer（机电设计） ─────────────────────────
    {
        "workflow_id": "AKO_mep_engineer",
        "name": "AKO_mep_engineer",
        "spoke_type": "agent",
        "entry_module": "agents.ako_mep_engineer",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "mep_output",
        "description": "机电设计：暖通/给排水/电气负荷计算与管线综合",
        "status": "registered",
        "source_dir": "D:/AKO_mep_engineer",
        "invoke_mode": "importlib",
    },
    # ── AKO_interior_designer（室内设计） ─────────────────────
    {
        "workflow_id": "AKO_interior_designer",
        "name": "AKO_interior_designer",
        "spoke_type": "agent",
        "entry_module": "agents.ako_interior_designer",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "interior_output",
        "description": "室内设计：空间规划、材料搭配、软装方案、效果图生成",
        "status": "registered",
        "source_dir": "D:/AKO_interior_designer",
        "invoke_mode": "importlib",
    },
    # ── AKO_landscape（景观设计） ────────────────────────────
    {
        "workflow_id": "AKO_landscape",
        "name": "AKO_landscape",
        "spoke_type": "agent",
        "entry_module": "agents.ako_landscape",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "landscape_output",
        "description": "景观设计：绿化配置、景观布局、海绵城市计算",
        "status": "registered",
        "source_dir": "D:/AKO_landscape",
        "invoke_mode": "importlib",
    },
    # ── AKO_project_manager（项目管理） ──────────────────────
    {
        "workflow_id": "AKO_project_manager",
        "name": "AKO_project_manager",
        "spoke_type": "agent",
        "entry_module": "agents.ako_project_manager",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "project_output",
        "description": "项目管理：进度编排、资源调度、里程碑跟踪、风险预警",
        "status": "registered",
        "source_dir": "D:/AKO_project_manager",
        "invoke_mode": "importlib",
    },
    # ── AKO_cost_estimator（造价估算） ───────────────────────
    {
        "workflow_id": "AKO_cost_estimator",
        "name": "AKO_cost_estimator",
        "spoke_type": "agent",
        "entry_module": "agents.ako_cost_estimator",
        "entry_function": "run",
        "required_kb_ids": ["ako_cost_database"],
        "output_dir": "cost_output",
        "description": "造价估算：工程量清单、综合单价分析、税金汇总、概预算编制",
        "status": "registered",
        "source_dir": "D:/AKO_cost_estimator",
        "invoke_mode": "importlib",
    },
    # ── AKO_bim_exporter（BIM导出） ──────────────────────────
    {
        "workflow_id": "AKO_bim_exporter",
        "name": "AKO_bim_exporter",
        "spoke_type": "agent",
        "entry_module": "agents.ako_bim_exporter",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "bim_output",
        "description": "BIM导出：IFC/GLTF/Revit 多格式转换与模型轻量化",
        "status": "registered",
        "source_dir": "D:/AKO_bim_exporter",
        "invoke_mode": "importlib",
    },
    # ── AKO_document_writer（文档撰写） ──────────────────────
    {
        "workflow_id": "AKO_document_writer",
        "name": "AKO_document_writer",
        "spoke_type": "agent",
        "entry_module": "agents.ako_document_writer",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "document_output",
        "description": "文档撰写：设计说明、技术报告、投标书自动撰写",
        "status": "registered",
        "source_dir": "D:/AKO_document_writer",
        "invoke_mode": "importlib",
    },
    # ── AKO_safety_inspector（安全巡检） ─────────────────────
    {
        "workflow_id": "AKO_safety_inspector",
        "name": "AKO_safety_inspector",
        "spoke_type": "agent",
        "entry_module": "agents.ako_safety_inspector",
        "entry_function": "run",
        "required_kb_ids": ["ako_safety_codes"],
        "output_dir": "safety_output",
        "description": "安全巡检：施工现场安全隐患识别、整改通知生成",
        "status": "registered",
        "source_dir": "D:/AKO_safety_inspector",
        "invoke_mode": "importlib",
    },
    # ── AKO_quality_inspector（质量检查） ────────────────────
    {
        "workflow_id": "AKO_quality_inspector",
        "name": "AKO_quality_inspector",
        "spoke_type": "agent",
        "entry_module": "agents.ako_quality_inspector",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "quality_output",
        "description": "质量检查：施工质量抽检记录、偏差分析、验收报告",
        "status": "registered",
        "source_dir": "D:/AKO_quality_inspector",
        "invoke_mode": "importlib",
    },
    # ── AKO_scheduler（施工排期） ───────────────────────────
    {
        "workflow_id": "AKO_scheduler",
        "name": "AKO_scheduler",
        "spoke_type": "agent",
        "entry_module": "agents.ako_scheduler",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "schedule_output",
        "description": "施工排期：甘特图生成、关键路径计算、资源冲突检测",
        "status": "registered",
        "source_dir": "D:/AKO_scheduler",
        "invoke_mode": "importlib",
    },
    # ── AKO_surveyor（测量测绘） ────────────────────────────
    {
        "workflow_id": "AKO_surveyor",
        "name": "AKO_surveyor",
        "spoke_type": "agent",
        "entry_module": "agents.ako_surveyor",
        "entry_function": "run",
        "required_kb_ids": [],
        "output_dir": "survey_output",
        "description": "测量测绘：地形数据处理、土方计算、坐标转换",
        "status": "registered",
        "source_dir": "D:/AKO_surveyor",
        "invoke_mode": "importlib",
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
