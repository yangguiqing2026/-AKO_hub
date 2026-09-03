# -*- coding: utf-8 -*-
"""
AKO Hub — AKO_standard_agent 适配器（importlib 模式，2026-09-03 批2 全接通）

D:/AKO/AKO_standard_agent 企业标准起草（纯本地模板链，零 LLM/网络）：
spec_from_file_location 延迟加载其仓库 spoke.run（不拖慢 hub 启动），
空/异常一律三字段优雅返回。

调用链：task_executor → agents.ako_standard_adapter.run(**payload)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

AGENT_DIR = Path(r"D:/AKO/AKO_standard_agent")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """SpokeAdapter 兼容入口：企业标准起草任务。"""
    try:
        spoke_path = AGENT_DIR / "spoke.py"
        spec = importlib.util.spec_from_file_location("ako_standard_spoke", str(spoke_path))
        if spec is None or spec.loader is None:
            return {"output_files": [], "summary": "", "error": f"standard spoke 缺失：{spoke_path}"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run(
            intent=intent,
            project_tag=project_tag,
            _hub_output_dir=_hub_output_dir,
            _hub_db_path=_hub_db_path,
            _hub_chroma_root=_hub_chroma_root,
            _hub_file_root=_hub_file_root,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "output_files": [],
            "summary": "standard 适配器调用失败",
            "error": f"{type(exc).__name__}: {exc}",
        }


if __name__ == "__main__":
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ret = run(intent="起草企业标准", _hub_output_dir=td)
    print(json.dumps(ret, ensure_ascii=False, indent=2))
