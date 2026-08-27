"""
AKO Hub — Agent 适配器包

本包包含已注册到 AKO Hub 的核心 Spoke 适配器：
- AKO_architect_agent（建筑结构设计）
- AKO_drawing_inspector（图纸质检）
- AKO_image_analyzer（图像分析）
- AKO_law_agent（法律审查与合规校验）

适配器职责：
1. 将 Master Graph 的 payload 转换为外部 Agent/工作流可识别的参数。
2. 调用外部 Agent 或生成占位结果文件。
3. 返回标准化结果字典，供 FileBus 注册。

文档编号: AGE-TECH-AKO-HUB-001 §6.3
"""

from .ako_architect_adapter import run as run_architect
from .ako_drawing_inspector import run as run_drawing_inspector
from .ako_image_analyzer import run as run_image_analyzer
from .ako_law_adapter import run as run_law
from .ako_geo_adapter import run as run_geo

__all__ = [
    "run_architect",
    "run_drawing_inspector",
    "run_image_analyzer",
    "run_law",
    "run_geo",
]