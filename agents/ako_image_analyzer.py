"""
AKO Hub — AKO_image_analyzer 适配器

文档编号: AGE-TECH-AKO-HUB-001 §6.3

职责：
1. 接收 Master Graph 通过 payload 下发的图像文件路径与输出目录。
2. 调用本地 AKO_image_analyzer 工作流（LangGraph 状态机，位于 E:\\AKO_image_analyzer）。
3. 将图像分析报告写入 _hub_output_dir，并返回文件路径。

调用链：
    Master Graph → agents.ako_image_analyzer.run(**payload)
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# 默认外部工作流目录（可通过 payload 覆盖）
DEFAULT_WORKFLOW_DIR = Path("D:/AKO/AKO_image_analyzer_agent")
DEFAULT_ENTRY_SCRIPT = "run.py"


def _write_stub_result(output_dir: Path, summary: str, files: List[str]) -> None:
    """当无法调用外部工作流时，生成占位结果文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stub_path = output_dir / f"stub_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    stub_path.write_text(
        json.dumps(
            {
                "agent": "AKO_image_analyzer",
                "summary": summary,
                "output_files": files,
                "generated_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run(
    intent: str = "",
    project_tag: str = "taoli",
    image_path: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    workflow_dir: Optional[str] = None,
    entry_script: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    AKO_image_analyzer 适配器入口。

    Args:
        intent: 任务意图，如 "图像分析" / "缺陷识别" / "施工现场验收"。
        project_tag: 项目标签，如 taoli。
        image_path: 待分析的图像文件路径（绝对或相对于 file_root）。
        _hub_output_dir: Master Graph 下发的产出目录（绝对路径）。
        _hub_db_path: 元数据库路径。
        _hub_chroma_root: Chroma 根目录。
        _hub_file_root: 文件总线根目录。
        workflow_dir: 外部工作流目录（可选）。
        entry_script: 外部工作流入口脚本（可选）。
        **kwargs: 透传其他参数。

    Returns:
        {"output_files": [...], "summary": str, "error": str|None}
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    external_dir = Path(workflow_dir) if workflow_dir else DEFAULT_WORKFLOW_DIR
    script = entry_script or DEFAULT_ENTRY_SCRIPT
    external_script = external_dir / script

    output_files: List[str] = []
    summary = "AKO_image_analyzer 未执行实际推理"
    error = None

    if external_dir.exists() and external_script.exists():
        try:
            env = os.environ.copy()
            env["AKO_HUB_OUTPUT_DIR"] = str(output_dir)
            env["AKO_HUB_PROJECT_TAG"] = project_tag
            env["AKO_HUB_INTENT"] = intent
            env["AKO_HUB_IMAGE_PATH"] = image_path
            # 修复 Windows 中文编码问题
            env["PYTHONIOENCODING"] = "utf-8"

            cmd = [sys.executable, str(external_script), "--intent", intent, "--project", project_tag]
            if image_path:
                cmd.extend(["--image", image_path])

            result = subprocess.run(
                cmd,
                cwd=str(external_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )

            if result.returncode == 0:
                summary = f"AKO_image_analyzer 外部调用成功：{intent}"
                output_files = [str(p) for p in output_dir.rglob("*") if p.is_file()]
            else:
                error = f"外部工作流返回非零退出码 {result.returncode}: {result.stderr}"
        except subprocess.TimeoutExpired:
            error = "外部工作流调用超时（600 秒）"
        except Exception as e:
            error = f"外部工作流调用失败: {type(e).__name__}: {e}"
    else:
        summary = f"AKO_image_analyzer 占位执行：{intent}（未检测到外部工作流目录 {external_dir}）"
        _write_stub_result(output_dir, summary, [])
        output_files = [str(p) for p in output_dir.rglob("*") if p.is_file()]

    return {
        "output_files": output_files,
        "summary": summary,
        "error": error,
    }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_image_analyzer_outputs")
    ret = run(intent="图像分析", project_tag="taoli", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))