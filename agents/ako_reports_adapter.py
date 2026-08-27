"""
AKO Hub — AKO_reports 适配器 (subprocess 模式)

文档编号: AGE-TECH-AKO-HUB-001 §6.3

职责：
1. 从 stdin 读取 Hub 下发的 JSON payload。
2. 调用 AKO_Report_Template 的 generate_report() 生成 HTML 报告。
3. 将产出写入 _hub_output_dir，完成后写入 _DONE.json。
4. 以 JSON 格式返回 {"output_files": [...], "summary": "...", "error": null} 到 stdout。

调用链：
    Master Graph → subprocess.run() → ako_reports_adapter.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# Report Template 路径
REPORT_TEMPLATE_DIR = Path("D:/AKO/AKO_hub/reports_templates")
REPORT_SCRIPTS_DIR = REPORT_TEMPLATE_DIR / "scripts"

# 确保脚本目录可导入
if str(REPORT_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_SCRIPTS_DIR))


def run(
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    config: Optional[Dict[str, Any]] = None,
    project_dir: str = "",
    template_dir: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    AKO_reports 适配器入口（供 Hub workflow_caller 直接调用，也支持 subprocess stdin 调用）。

    Args:
        _hub_output_dir: Master Graph 下发的产出目录。
        config: 报告配置字典（将序列化为 JSON 文件传给 generate_report）。
        project_dir: 项目图片目录（可选，覆盖自动扫描）。
        template_dir: 模板目录（可选，默认 REPORT_TEMPLATE_DIR/template）。
        **kwargs: 透传其他参数。

    Returns:
        {"output_files": [...], "summary": str, "error": str|None}
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else REPORT_TEMPLATE_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_files: List[str] = []
    summary = ""
    error = None

    try:
        from ako_report_generator import generate_report

        # 1. 写入临时配置文件
        config_data = config or {}
        config_path = output_dir / f"_hub_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        config_path.write_text(
            json.dumps(config_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 2. 确定模板目录
        tmpl_dir = template_dir or str(REPORT_TEMPLATE_DIR / "template")

        # 3. 调用报告生成器
        result_path = generate_report(
            config_path=str(config_path),
            template_dir=tmpl_dir,
            output_dir=str(output_dir),
        )

        # 4. 收集产出文件
        output_files = [str(p) for p in output_dir.rglob("*") if p.is_file()]
        summary = f"报告生成完成: {result_path}"

    except ImportError as e:
        error = f"导入 ako_report_generator 失败: {e}"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    # 5. 写入 _DONE.json（subprocess 完成信号）
    done_file = output_dir / "_DONE.json"
    done_data = {
        "output_files": output_files,
        "summary": summary,
        "error": error,
        "finished_at": datetime.now().isoformat(),
    }
    done_file.write_text(json.dumps(done_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_files": output_files,
        "summary": summary,
        "error": error,
    }


def _run_from_stdin() -> None:
    """从 stdin 读取 JSON payload，调用 run()，输出 JSON 到 stdout。"""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        result = {"output_files": [], "summary": "", "error": f"stdin JSON 解析失败: {e}"}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    result = run(**payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    _run_from_stdin()
