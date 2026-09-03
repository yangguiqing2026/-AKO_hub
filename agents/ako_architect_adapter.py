# -*- coding: utf-8 -*-
"""
AKO Hub — AKO_architect_agent 适配器

将 D:/AKO/AKO_architect_agent 包装为 Hub Spoke（importlib 模式，样板同 writer/intake）。

职责：
1. sys.path 注入 agent 仓库根 + AKO_shared 共享命名模块。
2. 延迟导入 agent 侧 spoke（agent 依赖重，导入失败不拖慢 hub 启动，错误透传三字段）。
3. 人工在环约定：architect 真实执行推进至"构思确认待命点"
   （human_approval_status=pending），不无人化跑文生图链。

调用链：
    task_executor → agents.ako_architect_adapter.run(**payload)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

AGENT_DIR = Path(r"D:\AKO\AKO_architect_agent")
SHARED_DIR = Path(r"D:\AKO\AKO_shared")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """SpokeAdapter 兼容入口：建筑设计任务（人工在环）。"""
    try:
        import importlib.util

        spoke_path = AGENT_DIR / "spoke.py"
        spec = importlib.util.spec_from_file_location("ako_architect_spoke", str(spoke_path))
        if spec is None or spec.loader is None:
            return {"output_files": [], "summary": "", "error": f"architect spoke 缺失：{spoke_path}"}
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
            "summary": "architect 适配器调用失败",
            "error": f"{type(exc).__name__}: {exc}",
        }


if __name__ == "__main__":
    # 本地快速测试（dry-run，无需 architect 依赖）
    import json
    import os
    import tempfile

    os.environ["AKO_HUB_SPOKE_DRYRUN"] = "1"
    with tempfile.TemporaryDirectory() as td:
        ret = run(intent="结构计算", project_tag="taoli", _hub_output_dir=td)
    print(json.dumps(ret, ensure_ascii=False, indent=2))
