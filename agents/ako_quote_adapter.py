"""
AKO Hub — AKO_quote 适配器
将 D:\AKO_quote_agent (装配式建筑报价引擎) 包装为 Hub Spoke。
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_quote_agent\ako_quote_agent")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。从 intent/kwargs 提取表单数据 → calculate_quote → JSON 文件。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 提取参数（简单关键词匹配）
    area = kwargs.get("area", 100.0)
    wall_type = kwargs.get("wall_type", "外墙")
    thickness = kwargs.get("thickness", 150)
    project_name = kwargs.get("project_name", project_tag)
    contact = kwargs.get("contact", "")
    phone = kwargs.get("phone", "")
    box_type = kwargs.get("box_type", None)
    transport_distance = kwargs.get("transport_distance", 50)

    # intent 中文解析：面积/墙型/厚度
    if intent:
        import re as _re
        area_match = _re.search(r"(\d+)\s*[平㎡]", intent)
        if area_match:
            area = float(area_match.group(1))
        if "内墙" in intent:
            wall_type = "内墙"
        elif "隔墙" in intent:
            wall_type = "隔墙"
        elif "外墙" in intent:
            wall_type = "外墙"
        thick_match = _re.search(r"(\d+)\s*mm", intent)
        if thick_match:
            thickness = int(thick_match.group(1))
        name_match = _re.search(r"项目[：:]\s*(\S+)", intent)
        if name_match:
            project_name = name_match.group(1)

    form_data = {
        "project_name": project_name,
        "area": area,
        "wall_type": wall_type,
        "thickness": thickness,
        "contact": contact,
        "phone": phone,
        "box_type": box_type,
        "transport_distance": transport_distance,
    }

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from quote_engine import calculate_quote

        result = calculate_quote(form_data)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quote_file = output_dir / f"quote_{project_name}_{timestamp}.json"
        output_data = {
            "input": form_data,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        }
        quote_file.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = (
            f"报价完成: {project_name}, {area}㎡ {wall_type} {thickness}mm, "
            f"总计 {result['total']:.2f} 元"
        )

        return {
            "output_files": [str(quote_file)],
            "summary": summary,
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_quote 导入失败: {e}。请确认 D:\\AKO_quote_agent 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_quote_outputs")
    ret = run(
        intent="报价: 200㎡外墙150mm",
        project_tag="taoli_test",
        _hub_output_dir=str(test_dir),
    )
    print(json.dumps(ret, ensure_ascii=False, indent=2))
