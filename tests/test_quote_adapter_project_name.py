"""quote adapter 抬头项目名（2026-09-14）。

背景：实测单号 F-AKO_akodoc_20260909_100807，报价书抬头印的是域默认值
`taoli` 而非用户输入的项目名。根因是 intake 侧项目名门禁未触发
（已在 ako_intake/services/ambiguity_detector.py 放宽），本文件守住适配器
这一侧的兜底行为：**项目名真落到默认值时不得静默**。

兜底本身保留——旧载荷/直接调用等场景仍会走到它，只是产出摘要里必须显式标注，
否则「抬头错了」这件事只能靠人翻 PDF 才发现。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

ADAPTER = Path(r"D:\AKO\AKO_hub\agents\ako_quote_adapter.py")

DEFAULT_TAG = "taoli"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ako_quote_adapter_pn_ut", str(ADAPTER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ako_quote_adapter_pn_ut"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class _FakeQuote:
    def calculate_quote(self, form_data: dict) -> dict:
        return {**form_data, "total": 1.0, "material_items": {}, "indirect_items": {}}


def _run(mod: ModuleType, tmp_path: Path, monkeypatch, **kwargs) -> Dict[str, Any]:
    monkeypatch.setitem(sys.modules, "quote_engine", _FakeQuote())
    monkeypatch.setitem(sys.modules, "pdf_generator", ModuleType("pdf_generator"))
    return mod.run(_hub_output_dir=str(tmp_path), **kwargs)


def test_default_header_is_flagged_in_summary(tmp_path, monkeypatch) -> None:
    """未提供项目名 → 抬头落域默认值，摘要必须显式标注，不得静默。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               action="生成",
               raw_input="生成一个345平米的3层住宅的陶粒墙板报价书",
               project_tag=DEFAULT_TAG)
    assert out["error"] is None
    assert DEFAULT_TAG in out["summary"]
    assert "默认" in out["summary"], f"未标注默认抬头：{out['summary']!r}"


def test_explicit_project_name_not_flagged(tmp_path, monkeypatch) -> None:
    """用户给了项目名 → 摘要不得出现默认抬头标注。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               project_name="桐木岭城市微更新商业体",
               action="出报价", raw_input="外墙300平方米", project_tag=DEFAULT_TAG)
    assert "桐木岭城市微更新商业体" in out["summary"]
    assert "默认" not in out["summary"], f"不应标注默认抬头：{out['summary']!r}"


def test_project_name_from_text_not_flagged(tmp_path, monkeypatch) -> None:
    """项目名从原文「项目：X」抽到时，同样不算默认抬头。"""
    mod = _load()
    out = _run(mod, tmp_path, monkeypatch,
               action="出报价", raw_input="项目：翠微小区改造 外墙300平方米",
               project_tag=DEFAULT_TAG)
    assert "翠微小区改造" in out["summary"]
    assert "默认" not in out["summary"], f"不应标注默认抬头：{out['summary']!r}"
