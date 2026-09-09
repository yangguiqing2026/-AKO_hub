"""quote adapter 面积解析（2026-09-09 回归）：
raw_input 透传后文本可提取；kwargs 显式值不被文本覆盖；支持小数与平方米变体。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Any

ADAPTER = Path(r"D:\AKO\AKO_hub\agents\ako_quote_adapter.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ako_quote_adapter_ut", str(ADAPTER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ako_quote_adapter_ut"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class _FakeQuote:
    def __init__(self) -> None:
        self.captured: Dict[str, Any] = {}

    def calculate_quote(self, form_data: dict) -> dict:
        self.captured = dict(form_data)
        return {**form_data, "total": 1.0, "material_items": {}, "indirect_items": {}}


def _run(mod: ModuleType, tmp_path: Path, monkeypatch, **kwargs) -> dict:
    fake = _FakeQuote()
    # quote_engine / pdf_generator 均走 sys.modules mock（adapter 的 from ... import 命中缓存）
    monkeypatch.setitem(sys.modules, "quote_engine", fake)
    monkeypatch.setitem(sys.modules, "pdf_generator", ModuleType("pdf_generator"))
    out = mod.run(_hub_output_dir=str(tmp_path), **kwargs)
    out["_form"] = fake.captured
    return out


def test_area_from_raw_input(tmp_path, monkeypatch) -> None:
    """raw_input 含「按500平方米」→ area=500（此前载荷无原文落默认 100）。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               action="请给我出报价单吧",
               raw_input="帮我按500平方米外墙150mm厚出一份报价",
               project_tag="taoli")
    assert out["_form"]["area"] == 500.0
    assert out["_form"]["wall_type"] == "外墙"
    assert out["_form"]["thickness"] == 150


def test_area_semantic_prefers_after_面积_keyword(tmp_path, monkeypatch) -> None:
    """「共300㎡其中生活区面积80㎡」→ 取 80（面积语义最近），非全文第一个 300。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               action="出报价", raw_input="项目共300㎡，其中生活区面积80平方米", project_tag="taoli")
    assert out["_form"]["area"] == 80.0


def test_decimal_area(tmp_path, monkeypatch) -> None:
    """123.5㎡（小数）可解析（原正则只匹配整数 → 落默认 100）。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch, action="出报价", raw_input="外墙123.5平方米", project_tag="taoli")
    assert out["_form"]["area"] == 123.5


def test_explicit_kwargs_area_not_overridden(tmp_path, monkeypatch) -> None:
    """结构化显式 area=600 不被文本里的 500㎡ 覆盖。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               area=600, wall_type="内墙",
               action="出报价", raw_input="帮我按500平方米外墙报价", project_tag="taoli")
    assert out["_form"]["area"] == 600.0
    assert out["_form"]["wall_type"] == "内墙"


def test_no_area_in_text_falls_back_to_default(tmp_path, monkeypatch) -> None:
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch, action="出个报价", raw_input="帮我出份报价", project_tag="taoli")
    assert out["_form"]["area"] == 100.0  # 默认


def test_project_name_strip_repeat_prefix(tmp_path, monkeypatch) -> None:
    """2026-09-09：复述式抬头兜底清洗（“测试项目名称是测试项目A” → “测试项目A”）。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               project_name="测试项目名称是测试项目A",
               action="出报价", raw_input="外墙500平方米", project_tag="taoli")
    assert out["_form"]["project_name"] == "测试项目A"
