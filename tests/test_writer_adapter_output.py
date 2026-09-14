"""writer 适配器输出路径（2026-09-14）。

背景：writer 产物原本写在自己仓库的 output/ 下，适配器再 shutil.copy2 一份到
hub 的 file_bus（工作台下载区）—— 同一产物存两份，且工作台只能下到拷贝件。
现 writer 的 OUTPUT_ROOT 直接指向 hub 的 file_bus/writer_output，
适配器不再拷贝，直接注册原位产物。

本文件守住"不再拷第二份"这一约束：产物列首位必须是 writer 原位路径，
且 hub 输出目录里不得冒出同名副本。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

ADAPTER = Path(r"D:\AKO\AKO_hub\agents\ako_writer_adapter.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ako_writer_adapter_ut", str(ADAPTER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ako_writer_adapter_ut"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _install_fakes(docx_path: Path) -> None:
    """预置 ako_writer 假包：_load_bootstrap 见 sys.modules 已有即跳过真实加载。"""
    spoke_mod = ModuleType("ako_writer.spoke")
    models_mod = ModuleType("ako_writer.models")

    class _FakeSpoke:
        def create_task(self, contract: Any):
            async def _c() -> str:
                return "WR-TEST-001"

            return _c()

        def get_task_status(self, task_id: str):
            async def _s() -> Dict[str, Any]:
                return {
                    "formatted_docx": {"path": str(docx_path)},
                    "current_node": "N5_complete",
                    "human_approval_status": "approved",
                }

            return _s()

    class _InputContract:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    class _TopicCard:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    spoke_mod.WriterSpoke = _FakeSpoke  # type: ignore[attr-defined]
    models_mod.InputContract = _InputContract  # type: ignore[attr-defined]
    models_mod.TopicCard = _TopicCard  # type: ignore[attr-defined]
    sys.modules["ako_writer"] = ModuleType("ako_writer")
    sys.modules["ako_writer.spoke"] = spoke_mod
    sys.modules["ako_writer.models"] = models_mod


def test_registers_writer_output_in_place_without_copy(tmp_path, monkeypatch) -> None:
    mod = _load()
    docx = tmp_path / "AKO_article_20990101_000000.docx"
    docx.write_bytes(b"fake-docx")

    hub_out = tmp_path / "hub_out"
    _install_fakes(docx)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0)  # 免等真实轮询间隔

    out = mod.run(_hub_output_dir=str(hub_out), topic="陶粒墙板在城市更新的运用")

    assert out["error"] is None, out
    assert out["output_files"][0] == str(docx), "产物列首位须为 writer 原位路径"
    assert not (hub_out / docx.name).exists(), "不得再在 hub 输出目录拷出第二份"
    # 状态回执仍随附输出（适配器自身产出，与 writer 产物无关）
    assert any(f.endswith(f"writer_task_WR-TEST-001.json") for f in out["output_files"])
