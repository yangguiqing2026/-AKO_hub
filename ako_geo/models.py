"""
AKO Hub — ako_geo Pydantic 数据模型
models.py: 定义 GEO Spoke 的核心数据结构。

文档编号: AGE-TECH-AKO-GEO-001 §2
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── 枚举类型 ─────────────────────────────────────────────────────────

class SensitivityLevel(str, Enum):
    """内容敏感度等级。"""
    P0 = "P0"  # 不可公开
    P1 = "P1"  # 脱敏后可公开
    P2 = "P2"  # 完全公开


class AgentSource(str, Enum):
    """素材来源 Agent 枚举。"""
    ARCHITECT_AGENT = "architect_agent"
    BUSINESS_AGENT = "business_agent"
    WORKFLOW = "workflow"
    IMAGE_ANALYZER = "image_analyzer"
    CHAT = "chat"
    KNOWLEDGE = "knowledge"


class ReviewStatus(str, Enum):
    """审核状态。"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    FAILED = "failed"      # 超过最大驳回次数
    SKIPPED = "skipped"    # sensitivity=P0 跳过


class Platform(str, Enum):
    """目标发布平台。"""
    ZHIHU = "zhihu"
    WECHAT = "wechat"
    DOUYIN = "douyin"
    BAIJIA = "baijia"


# ── 核心数据模型 ─────────────────────────────────────────────────────

class GeoSource(BaseModel):
    """
    geo.yaml 素材协议的数据模型。
    
    各业务 Agent 在输出目录中放置 geo.yaml，ako_geo 扫描后解析为此模型。
    """
    # 来源文件路径（非 geo.yaml 字段，扫描时附加）
    source_path: Optional[Path] = Field(default=None, exclude=True)
    
    # geo.yaml 标准字段
    agent: AgentSource = Field(..., description="素材来源 Agent")
    task_id: str = Field(..., description="原任务编号，如 ARCH-2025-001")
    created_at: str = Field(..., description="ISO 8601 时间戳")
    title: str = Field(..., max_length=50, description="成果标题，≤50字")
    public_abstract: str = Field(..., description="可公开摘要，50-500字")
    key_claims: List[str] = Field(default_factory=list, description="原子级断言列表，每条必须含量化值")
    geo_tags: List[str] = Field(default_factory=list, description="话题标签")
    sensitivity: SensitivityLevel = Field(default=SensitivityLevel.P0, description="敏感度等级")
    business_ref: Optional[str] = Field(default=None, description="关联 business_agent 项目编号")
    related_docs: Optional[List[str]] = Field(default=None, description="关联知识库文档 ID 列表")
    output_files: Optional[List[str]] = Field(default=None, description="素材文件相对路径列表")
    
    # 校验状态（内部使用）
    validation_errors: List[str] = Field(default_factory=list, exclude=True)
    validation_warnings: List[str] = Field(default_factory=list, exclude=True)
    content_hash: Optional[str] = Field(default=None, exclude=True, description="geo.yaml 内容 MD5，用于去重")

    @field_validator("created_at")
    @classmethod
    def validate_iso8601(cls, v: str) -> str:
        """验证 ISO 8601 时间格式。"""
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"created_at 必须是 ISO 8601 格式，实际: {v}")
        return v


class KeyClaim(BaseModel):
    """
    原子级断言（key_claim）。
    
    每条必须含量化值（数字+单位），如 "承重达到 500 kg/m²"。
    """
    text: str = Field(..., description="断言原文")
    has_quantity: bool = Field(default=False, description="是否包含量化值")
    quantity_value: Optional[str] = Field(default=None, description="提取的量化值")
    quantity_unit: Optional[str] = Field(default=None, description="提取的单位")


class PublishPack(BaseModel):
    """
    发布包：N6_Publish 节点的输出。
    
    包含可直接发布到目标平台的全部内容。
    """
    task_id: str = Field(..., description="来源任务 ID")
    platform: Platform = Field(..., description="目标平台")
    title: str = Field(..., description="发布标题")
    abstract: str = Field(..., description="发布摘要（用于 SEO/分享预览）")
    tags: List[str] = Field(default_factory=list, description="话题标签")
    content: str = Field(..., description="正文内容（Markdown 或纯文本）")
    cover_image_hint: Optional[str] = Field(default=None, description="封面图建议（关键词或路径）")
    meta: Dict[str, Any] = Field(default_factory=dict, description="发布元数据（状态、时间等）")
    
    # 元数据默认值
    def __init__(self, **data):
        super().__init__(**data)
        if "meta" not in data or not data["meta"]:
            self.meta = {
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "source_agent": data.get("source_agent", ""),
            }


class ReviewResult(BaseModel):
    """
    审核结果：N4_Review 节点的输出。
    """
    status: ReviewStatus = Field(..., description="审核状态")
    comment: Optional[str] = Field(default=None, description="审核意见（驳回/修改时填写）")
    reviewer: str = Field(default="human", description="审核人标识")
    reviewed_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="审核时间")


class GeoAnchor(BaseModel):
    """
    GEO 锚点：从知识库检索到的参考知识片段。
    """
    anchor_id: str = Field(..., description="锚点 ID")
    content: str = Field(..., description="锚点内容")
    source_collection: str = Field(default="", description="来源 Collection 名称")
    score: float = Field(default=0.0, description="相似度分数")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class FermentResult(BaseModel):
    """
    知识发酵结果：N8_Ferment 节点的输出。
    """
    new_anchors: List[Dict[str, Any]] = Field(default_factory=list, description="新回写的锚点")
    gaps: List[Dict[str, Any]] = Field(default_factory=list, description="标记的知识缺口")
    obsidian_note_path: Optional[Path] = Field(default=None, description="Obsidian 笔记路径")


# ── LangGraph State 模型 ─────────────────────────────────────────────

class GeoState(BaseModel):
    """
    LangGraph 状态机的完整状态定义。
    
    贯穿 N0_Scan → N8_Ferment 全流程。
    """
    # N0_Scan 输出
    sources: List[Path] = Field(default_factory=list, description="待扫描路径列表")
    candidates: List[GeoSource] = Field(default_factory=list, description="扫描到的候选素材")
    
    # N1_Filter 输出
    filtered: List[GeoSource] = Field(default_factory=list, description="过滤后的候选列表")
    
    # N2_Anchor 输出
    anchors: List[GeoAnchor] = Field(default_factory=list, description="检索到的知识锚点")
    context: str = Field(default="", description="聚合的上下文知识")
    
    # N3_Outline 输出
    outline: str = Field(default="", description="生成的大纲（Markdown）")
    
    # N4_Review 输出
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING, description="审核状态")
    review_comment: Optional[str] = Field(default=None, description="审核意见")
    review_loop_count: int = Field(default=0, description="当前审核循环次数")
    
    # N5_Format 输出
    content: str = Field(default="", description="平台适配后的正文内容")
    
    # N6_Publish 输出
    publish_pack: Optional[PublishPack] = Field(default=None, description="发布包")
    
    # N7_Store 输出
    file_paths: List[Path] = Field(default_factory=list, description="生成的文件路径列表")
    
    # N8_Ferment 输出
    new_anchors: List[Dict[str, Any]] = Field(default_factory=list, description="新回写的锚点")
    
    # 全局控制字段
    current_task_id: str = Field(default="", description="当前处理的任务 ID")
    current_platform: str = Field(default="", description="当前处理的目标平台")
    current_agent: str = Field(default="", description="当前素材来源 Agent")
    current_source: Optional[GeoSource] = Field(default=None, description="当前处理的 GeoSource")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    processed_task_ids: List[str] = Field(default_factory=list, description="已处理的 task_id 列表（去重）")

    class Config:
        arbitrary_types_allowed = True
