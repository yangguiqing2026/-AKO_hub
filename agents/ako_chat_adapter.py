"""
AKO Hub — AKO_chat 适配器
将 D:\AKO\AKO_hub (RAG 知识库对话系统) 包装为 Hub Spoke。

调用方式：
    Hub workflow_caller 通过 importlib 导入本模块，调用 run() 函数。
    run() 内部实例化 RAGService 并执行 chat()，返回标准 Spoke 输出。
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# 将 AKO_chat 源码加入路径
SOURCE_DIR = Path(r"D:\AKO\AKO_hub")
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))


def run(
    intent: str = "",
    project_tag: str = "taoli",
    kb_id: str = "all",
    question: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Spoke 适配器入口。

    Args:
        intent:  任务意图（如果 question 为空，用 intent 作为问题）
        question: 用户的具体问题（优先于 intent）
        kb_id:   知识库 ID（默认 "all"）
        project_tag: 项目标签
        _hub_*: Hub 下发的路径参数

    Returns:
        标准 Spoke 输出: {output_files, summary, error}
    """
    # 确定问题文本
    user_question = question or intent
    if not user_question:
        return {
            "output_files": [],
            "summary": "",
            "error": "未提供问题（intent 或 question 参数为空）",
        }

    # 设置 Hub 路径环境变量（供 RAGService 内部使用）
    if _hub_db_path:
        import os
        os.environ["AKO_HUB_ROOT"] = str(Path(_hub_db_path).parent)
        os.environ["AKO_KNOWLEDGE_ROOT"] = str(Path(_hub_chroma_root).parent)

    try:
        # 导入 AKO_chat 的 RAG 服务
        from services.rag_service import RAGService, RAGResponse

        # 实例化并调用
        service = RAGService()
        response: RAGResponse = service.chat(
            message=user_question,
            kb_id=kb_id,
        )

        # 将回答保存为文件
        output_files = []
        if _hub_output_dir:
            output_dir = Path(_hub_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            answer_file = output_dir / f"chat_response_{timestamp}.json"
            answer_data = {
                "question": user_question,
                "answer": response.answer,
                "references": [
                    {"index": r.index, "source": r.source, "preview": r.preview}
                    for r in response.references
                ],
                "kb_used": response.kb_used,
                "model_used": response.model_used,
                "latency_ms": response.latency_ms,
                "timestamp": datetime.now().isoformat(),
            }
            answer_file.write_text(
                json.dumps(answer_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_files.append(str(answer_file))

        # 生成摘要
        summary = response.answer[:200] if response.answer else "无回答"
        if response.error:
            summary = f"回答异常: {response.error}"

        return {
            "output_files": output_files,
            "summary": summary,
            "error": response.error,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_chat 导入失败: {e}。请确认 D:\\AKO_chat 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }
