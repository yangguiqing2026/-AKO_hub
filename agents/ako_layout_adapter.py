"""
AKO Hub — AKO_layout_agent 适配器
将 D:\AKO\AKO_layout_agent (智能排版) 包装为 Hub Spoke。
"""
import sys
import json
import io
from pathlib import Path
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO\AKO_layout_agent")
CONFIG_PATH = str(SOURCE_DIR / "AKO-Layout-Agent-Config-v2.1.json")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    action: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。根据 intent 调用排版流水线。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 推断 action
    if not action:
        action = "demo"  # 默认演示模式
        if any(kw in intent for kw in ["项目", "排版", "输出"]):
            action = "project"

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from src.page_assembler import PageAssembler
        from src.input_handler import InputHandler
        from src.render_engine import PDFRenderer
        from src.export_engine import JPGExporter, PPTExporter
        from src.layout_engine import P3HeartbeatLayout, get_default_heartbeat_items

        log_buf = io.StringIO()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with redirect_stdout(log_buf), redirect_stderr(log_buf):
            if action == "project":
                # 查找 input 目录下的项目文件夹
                input_dir = SOURCE_DIR / "input"
                project_folder = kwargs.get("project_folder", "")
                if project_folder:
                    project_path = input_dir / project_folder
                else:
                    folders = sorted([
                        d for d in input_dir.iterdir()
                        if d.is_dir() and d.name.startswith("AKO_")
                    ]) if input_dir.exists() else []
                    project_path = folders[0] if folders else None

                if project_path and project_path.exists():
                    handler = InputHandler(str(input_dir))
                    project_input = handler.load_folder(str(project_path))
                    assembler = PageAssembler(CONFIG_PATH)
                    pages = assembler.assemble(project_input, project_name=project_path.name)
                    # 渲染心跳预览
                    layout_engine = P3HeartbeatLayout(CONFIG_PATH)
                    layout = layout_engine.calculate(
                        heartbeat_items=get_default_heartbeat_items(),
                    )
                    renderer = PDFRenderer(CONFIG_PATH)
                    # 输出 PDF
                    pdf_path = output_dir / f"layout_{project_path.name}_{timestamp}.pdf"
                    renderer.render_multi_page_pdf(pages, str(pdf_path))
                    # 输出 JPG 预览
                    jpg_path = output_dir / f"layout_{project_path.name}_{timestamp}_preview.jpg"
                    JPGExporter(renderer).export_p3_jpg(layout, str(jpg_path))
                    output_files = [str(pdf_path), str(jpg_path)]
                    summary = f"排版完成: {project_path.name}, {len(pages)} 页"
                else:
                    output_files = []
                    summary = "无可用项目，请将项目放入 input/ 目录"
            else:
                # 演示模式
                from main import run_demo
                run_demo()
                # 收集 output 目录下的最新文件
                agent_output = SOURCE_DIR / "output"
                output_files = []
                if agent_output.exists():
                    for f in sorted(agent_output.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                        if f.is_file():
                            dest = output_dir / f.name
                            import shutil
                            shutil.copy2(str(f), str(dest))
                            output_files.append(str(dest))
                summary = f"排版演示完成，输出 {len(output_files)} 个文件"

        log_file = output_dir / f"layout_{action}_{timestamp}.log"
        log_file.write_text(log_buf.getvalue(), encoding="utf-8")

        return {
            "output_files": output_files + [str(log_file)],
            "summary": summary,
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_layout 导入失败: {e}。请确认 D:\\AKO_layout_agent 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_layout_outputs")
    ret = run(intent="排版演示", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))
