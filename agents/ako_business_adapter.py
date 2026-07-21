"""
AKO Hub — AKO_business 适配器
将 D:\AKO_business_agent (作战指挥系统) 包装为 Hub Spoke。

支持操作：
  - 生成报价单 (generate_quote) + 风险评估 (risk_report)
  - 每日作战简报 (daily_briefing)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_business_agent")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    project_id: str = "",
    action: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Spoke 适配器入口。

    Args:
        intent: 任务意图 ("商业分析" / "报价" / "简报" 等)
        action: 具体操作 — "quote"(报价单) / "risk"(风险评估) / "briefing"(简报) / "all"(全部)
        project_id: 目标项目 ID（用于报价和风险评估）
        _hub_*: Hub 下发的路径参数

    Returns:
        标准 Spoke 输出: {output_files, summary, error}
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 推断 action
    if not action:
        if "报价" in intent:
            action = "quote"
        elif "风险" in intent:
            action = "risk"
        elif "简报" in intent or "日报" in intent:
            action = "briefing"
        else:
            action = "all"

    output_files = []
    summary_parts = []

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from storage import load_projects, get_project, ensure_dirs
        from engines.doc_generator import DocGenerator
        ensure_dirs()

        if action in ("quote", "all"):
            _run_quote(output_dir, project_id, output_files, summary_parts, **kwargs)

        if action in ("risk", "all"):
            _run_risk(output_dir, project_id, output_files, summary_parts, **kwargs)

        if action in ("briefing", "all"):
            _run_briefing(output_dir, output_files, summary_parts)

        summary = "; ".join(summary_parts) if summary_parts else "未执行操作"
        return {
            "output_files": output_files,
            "summary": summary,
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_business 导入失败: {e}。请确认 D:\\AKO_business_agent 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


def _run_quote(output_dir: Path, project_id: str, output_files: list,
               summary_parts: list, **kwargs) -> None:
    """生成报价单"""
    from storage import get_project, load_projects
    from engines.doc_generator import DocGenerator

    project = None
    if project_id:
        project = get_project(project_id)
    if not project:
        projects = load_projects()
        active = [p for p in projects if hasattr(p, 'status') and p.status == "活跃"]
        if not active and projects:
            active = projects
        if active:
            project = active[0]

    if not project:
        summary_parts.append("无可用项目生成报价单")
        return

    gen = DocGenerator()
    filepath = gen.generate_quote(project)
    if filepath and Path(filepath).exists():
        # 复制到 Hub 输出目录
        import shutil
        dest = output_dir / Path(filepath).name
        shutil.copy2(filepath, dest)
        output_files.append(str(dest))
        summary_parts.append(f"报价单已生成: {project.name}")


def _run_risk(output_dir: Path, project_id: str, output_files: list,
              summary_parts: list, **kwargs) -> None:
    """生成风险评估"""
    from storage import get_project, load_projects
    from engines.doc_generator import DocGenerator

    project = None
    if project_id:
        project = get_project(project_id)
    if not project:
        projects = load_projects()
        active = [p for p in projects if hasattr(p, 'status') and p.status == "活跃"]
        if not active and projects:
            active = projects
        if active:
            project = active[0]

    if not project:
        summary_parts.append("无可用项目生成风险评估")
        return

    gen = DocGenerator()
    filepath = gen.generate_risk_report(project)
    if filepath and Path(filepath).exists():
        import shutil
        dest = output_dir / Path(filepath).name
        shutil.copy2(filepath, dest)
        output_files.append(str(dest))
        summary_parts.append(f"风险评估已生成: {project.name}")


def _run_briefing(output_dir: Path, output_files: list,
                  summary_parts: list) -> None:
    """生成每日简报"""
    import io
    from contextlib import redirect_stdout
    from cli.briefing import daily_briefing

    buf = io.StringIO()
    with redirect_stdout(buf):
        daily_briefing()

    content = buf.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    briefing_file = output_dir / f"daily_briefing_{timestamp}.txt"
    briefing_file.write_text(content, encoding="utf-8")
    output_files.append(str(briefing_file))
    summary_parts.append("每日简报已生成")


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_business_outputs")
    ret = run(intent="报价", project_tag="taoli", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))
