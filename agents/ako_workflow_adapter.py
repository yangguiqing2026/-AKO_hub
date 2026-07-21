"""
AKO Hub — AKO工作流 适配器
将 D:\AKO工作流 (陶粒墙板智能工作流) 包装为 Hub Spoke。

工作流内部使用 LangGraph StateGraph，节点包括：
  input_parser → retriever → technical_generator → business_generator
  → reverse_checker → quality_checker → legal_analysis → feasibility_study
  → output_formatter

本适配器：
  1. 将 Hub 参数映射为工作流初始状态
  2. 调用 app.invoke() 执行完整流程
  3. 收集输出文件，返回标准 Spoke 协议
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# 将 AKO工作流 源码加入路径
SOURCE_DIR = Path(r"D:\AKO工作流")
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))


def run(
    intent: str = "",
    project_tag: str = "taoli",
    user_input: str = "",
    input_file: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Spoke 适配器入口。

    Args:
        intent:     任务意图（如果 user_input 为空，用 intent 作为输入）
        user_input: 用户文本输入（优先于 intent）
        input_file: 输入文件路径（.docx / .pdf / .txt 等）
        project_tag: 项目标签
        _hub_*: Hub 下发的路径参数

    Returns:
        标准 Spoke 输出: {output_files, summary, error}
    """
    # 1. 确定输入
    text_input = user_input or intent
    error_msg = ""

    if input_file and not text_input:
        # 从文件提取文本
        try:
            os.chdir(SOURCE_DIR)  # file_parser 需要相对路径
            from file_parser import extract_text_from_file, is_supported_file
            if is_supported_file(input_file):
                text_input = extract_text_from_file(input_file)
            else:
                error_msg = f"不支持的文件格式: {input_file}"
        except Exception as e:
            error_msg = f"文件解析失败: {e}"

    if not text_input and not error_msg:
        return {
            "output_files": [],
            "summary": "",
            "error": "未提供输入（user_input / intent / input_file 均为空）",
        }

    if error_msg:
        return {
            "output_files": [],
            "summary": "",
            "error": error_msg,
        }

    # 2. 设置 Hub 环境变量（供工作流内部 KnowledgeHub 使用）
    if _hub_db_path:
        os.environ["AKO_HUB_ROOT"] = str(Path(_hub_db_path).parent)
    if _hub_chroma_root:
        os.environ["AKO_HUB_CHROMA_ROOT"] = _hub_chroma_root

    try:
        os.chdir(SOURCE_DIR)  # 工作流内部使用相对路径加载 prompts/
        from graph import app
        from state import WorkflowState
        from config import config

        # 3. 构造初始状态
        initial_state: WorkflowState = {
            "user_input": text_input,
            "input_type": "",
            "parsed_data": {},
            "missing_fields": [],
            "clarified": False,
            "queries": [],
            "retrieved": [],
            "current_mix": None,
            "target_performance": None,
            "technical_solution": None,
            "tech_validation_passed": False,
            "technical_iteration_count": 0,
            "business_draft": None,
            "market_data": None,
            "business_solution": None,
            "legal_analysis": None,
            "feasibility_result": None,
            "reverse_check": None,
            "quality_score": 0.0,
            "hallucination_check": None,
            "consistency_check": None,
            "human_review_required": False,
            "model_scores": None,
            "iteration_count": 0,
            "max_iterations": config.MAX_ITERATIONS,
            "human_feedback": None,
            "interrupt_point": None,
            "final_output": None,
            "output_format": config.OUTPUT_FORMAT,
            "document_path": None,
            "error": None,
        }

        # 4. 执行工作流
        result = app.invoke(initial_state)

        # 5. 收集输出文件
        output_files: List[str] = []
        doc_path = result.get("document_path")
        if doc_path and Path(doc_path).exists():
            output_files.append(str(doc_path))

        # 如果有 Hub 输出目录，复制文件
        if _hub_output_dir and doc_path and Path(doc_path).exists():
            import shutil
            out_dir = Path(_hub_output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = out_dir / f"workflow_{ts}{Path(doc_path).suffix}"
            shutil.copy2(doc_path, dest)
            output_files.append(str(dest))

        # 6. 生成摘要
        conclusion = result.get("final_conclusion", "未评估")
        quality = result.get("quality_score", 0.0)
        summary_parts = [
            f"工作流执行完成",
            f"结论: {conclusion}",
            f"质量评分: {quality}",
        ]
        if result.get("error"):
            summary_parts.append(f"错误: {result['error']}")
        summary = " | ".join(summary_parts)

        return {
            "output_files": output_files,
            "summary": summary,
            "error": result.get("error", ""),
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO工作流导入失败: {e}。请确认 D:\\AKO工作流 目录存在且 venv 依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }
