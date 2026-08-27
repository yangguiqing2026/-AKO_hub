"""
AKO Hub — AKO_architect_agent 适配器

文档编号: AGE-TECH-AKO-HUB-001 §6.3

职责：
1. 接收 Master Graph 通过 payload 下发的参数与输出目录。
2. 调用本地 AKO_architect_agent（位于 E:\\AKO_architect_agent 的独立推理体）。
3. 将产出文件写入 _hub_output_dir，并通过 FileBus 注册（本适配器返回产出路径）。

调用链：
    Master Graph → agents.ako_architect_adapter.run(**payload)
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# 默认外部 Agent 路径（可通过 payload 覆盖）
DEFAULT_AGENT_DIR = Path("D:/AKO/AKO_architect_agent")
DEFAULT_ENTRY_SCRIPT = "run.py"  # 外部 Agent 入口脚本，可调整


def _write_stub_result(output_dir: Path, summary: str, files: List[str]) -> None:
    """当无法调用外部 Agent 时，生成占位结果文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stub_path = output_dir / f"stub_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    stub_path.write_text(
        json.dumps(
            {
                "agent": "AKO_architect_agent",
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
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    agent_dir: Optional[str] = None,
    entry_script: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    AKO_architect_agent 适配器入口。

    Args:
        intent: 任务意图，如 "结构计算" / "节点设计" / "生成技术文档"。
        project_tag: 项目标签，如 taoli。
        _hub_output_dir: Master Graph 下发的产出目录（绝对路径）。
        _hub_db_path: 元数据库路径。
        _hub_chroma_root: Chroma 根目录。
        _hub_file_root: 文件总线根目录。
        agent_dir: 外部 Agent 目录（可选，覆盖默认 E:/AKO_architect_agent）。
        entry_script: 外部 Agent 入口脚本（可选）。
        **kwargs: 透传其他参数。

    Returns:
        {"output_files": [...], "summary": str, "error": str|None}
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    external_dir = Path(agent_dir) if agent_dir else DEFAULT_AGENT_DIR
    script = entry_script or DEFAULT_ENTRY_SCRIPT
    external_script = external_dir / script

    output_files: List[str] = []
    summary = "AKO_architect_agent 未执行实际推理"
    error = None

    # 尝试调用外部 Agent
    if external_dir.exists() and external_script.exists():
        try:
            env = os.environ.copy()
            env["AKO_HUB_OUTPUT_DIR"] = str(output_dir)
            env["AKO_HUB_PROJECT_TAG"] = project_tag
            env["AKO_HUB_INTENT"] = intent
            # 修复 Windows 中文编码问题
            env["PYTHONIOENCODING"] = "utf-8"

            result = subprocess.run(
                [sys.executable, str(external_script), "--intent", intent, "--project", project_tag],
                cwd=str(external_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )

            if result.returncode == 0:
                summary = f"AKO_architect_agent 外部调用成功：{intent}"
                # 外部 Agent 应将文件写入 output_dir，扫描后返回
                output_files = [str(p) for p in output_dir.rglob("*") if p.is_file()]
            else:
                error = f"外部 Agent 返回非零退出码 {result.returncode}: {result.stderr}"
        except subprocess.TimeoutExpired:
            error = "外部 Agent 调用超时（600 秒）"
        except Exception as e:
            error = f"外部 Agent 调用失败: {type(e).__name__}: {e}"
    else:
        # 未检测到外部 Agent，生成占位结果
        summary = f"AKO_architect_agent 占位执行：{intent}（未检测到外部 Agent 目录 {external_dir}）"
        _write_stub_result(output_dir, summary, [])
        output_files = [str(p) for p in output_dir.rglob("*") if p.is_file()]

    return {
        "output_files": output_files,
        "summary": summary,
        "error": error,
    }


if __name__ == "__main__":
    # 本地快速测试
    test_dir = Path("./tmp_ako_architect_outputs")
    ret = run(intent="结构计算", project_tag="taoli", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))