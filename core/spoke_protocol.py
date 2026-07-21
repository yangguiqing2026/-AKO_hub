"""
AKO Hub — Spoke 适配器协议定义
spoke_protocol.py: 所有 Spoke 必须实现此协议才能被 Hub 正确调用。

文档编号: AGE-TECH-AKO-HUB-001 §6.4

用途：
  1. 定义标准接口，新增 Spoke 时以此为模板。
  2. workflow_caller 节点在调用后校验返回值是否合规。
  3. 生成适配器代码时的参考规范。
"""

from typing import Protocol, Dict, Any, List, Optional, runtime_checkable


@runtime_checkable
class SpokeAdapter(Protocol):
    """
    Spoke 适配器标准接口。

    每个 Spoke 项目必须提供一个符合此签名的 run() 函数。
    Hub 的 workflow_caller 节点通过 importlib 动态导入后调用此函数。

    参数说明：
        intent:         任务意图（自然语言关键词）
        project_tag:    项目标签（如 "taoli"）
        _hub_output_dir:  Hub 下发的产出目录绝对路径
        _hub_db_path:     Hub 元数据库路径
        _hub_chroma_root: Hub ChromaDB 根目录
        _hub_file_root:   Hub 文件总线根目录
        **kwargs:         Spoke 自定义参数（从 payload 透传）

    返回值：
        {
            "output_files": List[str],  # 生成的文件绝对路径列表
            "summary": str,             # 执行摘要（1-2 句话）
            "error": Optional[str],     # 错误信息（None 表示成功）
        }
    """

    def run(
        self,
        intent: str = "",
        project_tag: str = "",
        _hub_output_dir: str = "",
        _hub_db_path: str = "",
        _hub_chroma_root: str = "",
        _hub_file_root: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]: ...


def validate_spoke_output(result: Any) -> tuple[bool, str]:
    """
    校验 Spoke 输出是否符合协议。

    Returns:
        (是否合规, 错误信息)
    """
    if not isinstance(result, dict):
        return False, f"返回值类型错误: 期望 dict，实际 {type(result).__name__}"

    # 必需字段
    if "output_files" not in result:
        return False, "缺少必需字段: output_files"

    if not isinstance(result["output_files"], list):
        return False, f"output_files 类型错误: 期望 list，实际 {type(result['output_files']).__name__}"

    # 可选字段类型校验
    if "summary" in result and not isinstance(result["summary"], str):
        return False, f"summary 类型错误: 期望 str，实际 {type(result['summary']).__name__}"

    # output_files 中的每个元素应该是字符串
    for i, f in enumerate(result["output_files"]):
        if not isinstance(f, str):
            return False, f"output_files[{i}] 类型错误: 期望 str，实际 {type(f).__name__}"

    return True, ""
