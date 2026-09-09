"""
AKO Hub — AKO_quote 适配器
将 D:/AKO/AKO_quote_agent (装配式建筑报价引擎) 包装为 Hub Spoke。
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO\AKO_quote_agent\ako_quote_agent")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。从 intent/action/kwargs 提取表单数据 → calculate_quote
    → JSON 数据 + PDF 报价单。

    2026-09-04 修复：
    1. 载荷文本源合并 intent 与 action——intake 大门投递载荷无顶层 intent，
       主文本在 action 字段，此前只读 intent → 工单全部落默认参数；
    2. 交付物补 PDF：复用 quote_agent 自带 pdf_generator（其标准产品流即 PDF），
       PDF 生成失败不阻断，仍回退 JSON 数据文件。
    """
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 参数提取：结构化 kwargs 显式值优先；缺失字段才回退文本解析（2026-09-09 修复：
    # 此前 kwargs.area 无条件被文本覆盖、raw_input 未并入致面积落默认 100㎡ 与输入不一致）
    _none = object()
    area_raw = kwargs.get("area", _none)
    wall_type_raw = kwargs.get("wall_type", _none)
    thickness_raw = kwargs.get("thickness", _none)
    area: float = float(area_raw) if area_raw not in (None, "", _none) else 100.0
    wall_type: str = str(wall_type_raw) if wall_type_raw not in (None, "", _none) else "外墙"
    thickness: int = int(thickness_raw) if thickness_raw not in (None, "", _none) else 150
    # 空串（专家模式未填/旧载荷）回退 project_tag，避免脏文件名与空抬头
    project_name = str(kwargs.get("project_name") or "").strip() or project_tag
    # 2026-09-09：清理复述式抬头（intake 澄清答复现已在源头剥离；此处兜底旧载荷
    # 与其他调用方——"测试项目名称是测试项目A" → "测试项目A"）
    import re as _re_pn
    project_name = (_re_pn.sub(r"^.*?项目(?:名|名称)?(?:是|叫|为|：|:)\s*", "", project_name) or project_name).strip() or project_tag
    contact = kwargs.get("contact", "")
    phone = kwargs.get("phone", "")
    box_type = kwargs.get("box_type", None)
    transport_distance = kwargs.get("transport_distance", 50)

    # 合并文本源：raw_input（intake 大门透传的用户原始需求全文，含报价参数）+ intent/action
    action = str(kwargs.get("action", "")).strip()
    raw_input_text = str(kwargs.get("raw_input") or "").strip()
    raw_text = " ".join(t for t in (raw_input_text, intent, action) if t)

    if raw_text:
        import re as _re
        # 面积：优先取「面积」语义后最近的一个数值+面积单位；否则全文第一个。
        # 支持小数（如 123.5㎡）与 平方米/平米/㎡ 变体。
        if area_raw in (None, "", _none):
            segment = raw_text
            idx = _re.search(r"面积", raw_text)
            if idx:
                segment = raw_text[idx.end():][:40]
            area_match = _re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)", segment)
            if area_match:
                area = float(area_match.group(1))
        if wall_type_raw in (None, "", _none):
            if "内墙" in raw_text:
                wall_type = "内墙"
            elif "隔墙" in raw_text:
                wall_type = "隔墙"
            elif "外墙" in raw_text:
                wall_type = "外墙"
        if thickness_raw in (None, "", _none):
            thick_match = _re.search(r"(\d+)\s*mm", raw_text)
            if thick_match:
                thickness = int(thick_match.group(1))
        name_match = _re.search(r"项目[：:]\s*(\S+)", raw_text)
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
        output_files = [str(quote_file)]

        # PDF 报价单（2026-09-04：quote_agent 标准交付物为 PDF；失败仅降级不阻断）
        task_ref = str(kwargs.get("wo_number") or kwargs.get("task_id") or "")
        try:
            from pdf_generator import generate_pdf

            pdf_path = generate_pdf(result, task_ref, output_dir=str(output_dir))
            output_files.append(pdf_path)
            summary += f"，PDF 报价单: {Path(pdf_path).name}"
        except ImportError as e:
            print(f"[WARN] ako_quote_adapter: pdf_generator 导入失败，仅输出 JSON: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] ako_quote_adapter: PDF 生成失败，仅输出 JSON: {type(e).__name__}: {e}")

        return {
            "output_files": output_files,
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
