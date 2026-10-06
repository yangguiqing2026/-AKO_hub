# -*- coding: utf-8 -*-
"""quote 适配器 action 载荷 + PDF 交付（2026-09-04 修复回归）。

背景：
1. intake 大门投递载荷无顶层 intent（歧义消解后的主文本在 action 字段），
   适配器此前只读 intent → action 工单全部落默认 taoli/100㎡ 默认参数；
2. 适配器此前只落 JSON 数据文件，未调用 quote_agent 自带 pdf_generator，
   导致对话回显交付物为 .json 而非 PDF 报价单。
"""
import importlib
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _run_module():
    return importlib.import_module("agents.ako_quote_adapter")


def test_action_text_drives_form_params():
    """复现修复①：仅给 action（intake 真实载荷形状）时，面积/墙型必须来自 action 文本。"""
    mod = _run_module()
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(
            project_tag="taoli",
            _hub_output_dir=td,
            action="修改250平米二层住宅外墙的报价方案",
            wo_number="WO-HAI-20260904-901",
        )
        assert result["error"] is None, result["error"]
        jsons = [p for p in result["output_files"] if p.endswith(".json")]
        assert jsons, "应产出 JSON 数据文件"
        data = json.loads(Path(jsons[0]).read_text(encoding="utf-8"))
        assert data["input"]["area"] == 250.0, f"action 面积未解析: {data['input']['area']}"
        assert data["input"]["wall_type"] == "外墙", data["input"]["wall_type"]


def test_intent_still_parses_area():
    """既有 intent 路径不得回归。"""
    mod = _run_module()
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="报价: 200㎡外墙150mm", project_tag="taoli_test", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        jsons = [p for p in result["output_files"] if p.endswith(".json")]
        data = json.loads(Path(jsons[0]).read_text(encoding="utf-8"))
        assert data["input"]["area"] == 200.0


def test_deliverable_includes_pdf():
    """修复②：交付物必须含 PDF 报价单（quote_agent pdf_generator），且文件真实落盘。"""
    mod = _run_module()
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(intent="报价: 200㎡外墙150mm", _hub_output_dir=td)
        assert result["error"] is None, result["error"]
        pdfs = [p for p in result["output_files"] if p.lower().endswith(".pdf")]
        assert pdfs, f"output_files 无 PDF: {result['output_files']}"
        assert Path(pdfs[0]).exists() and Path(pdfs[0]).stat().st_size > 0


def test_project_name_flows_into_json_and_pdf():
    """2026-09-04：载荷 project_name（intake 澄清所得）必须贯穿 form_data →
    calculate_quote result → PDF 抬头（JSON input 与 result 项目名一致即同源）。"""
    mod = _run_module()
    with tempfile.TemporaryDirectory() as td:
        result = mod.run(
            project_tag="taoli",
            _hub_output_dir=td,
            action="报价250平米外墙",
            project_name="桐木岭城市微更新商业体",
            wo_number="WO-HAI-20260904-902",
        )
        assert result["error"] is None, result["error"]
        jsons = [p for p in result["output_files"] if p.endswith(".json")]
        data = json.loads(Path(jsons[0]).read_text(encoding="utf-8"))
        assert data["input"]["project_name"] == "桐木岭城市微更新商业体"
        assert data["result"]["project_name"] == "桐木岭城市微更新商业体"
        pdfs = [p for p in result["output_files"] if p.lower().endswith(".pdf")]
        assert pdfs, "应产出 PDF"
        # 文件命名沿用引擎 project_name（非默认 taoli）
        assert "taoli" not in Path(pdfs[0]).name and Path(pdfs[0]).exists()
