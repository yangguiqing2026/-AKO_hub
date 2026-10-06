# -*- coding: utf-8 -*-
"""
AKO Hub — AKO_architect_agent 适配器

将 D:/AKO/AKO_architect_agent 包装为 Hub Spoke（importlib 模式，样板同 writer/intake）。

职责：
1. sys.path 注入 agent 仓库根 + AKO_shared 共享命名模块。
2. 延迟导入 agent 侧 spoke（agent 依赖重，导入失败不拖慢 hub 启动，错误透传三字段）。
3. 人工在环约定：architect 真实执行推进至"构思确认待命点"
   （human_approval_status=pending），不无人化跑文生图链。
4. 例外（2026-09-09 AKO_studio 拍板）：效果图/渲染类工单（action/scope/intent 命中
   效果图|渲染）由 spoke 自动渲染 4 视角出图（wanx 优先、SD 兜底），不经构思确认。

调用链：
    task_executor → agents.ako_architect_adapter.run(**payload)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

AGENT_DIR = Path(r"D:\AKO\AKO_architect_agent")
SHARED_DIR = Path(r"D:\AKO\AKO_shared")


def _synthesize_intent(intent: str, kwargs: Dict[str, Any]) -> str:
    """intent 为空时从 WO 透传字段（action/scope）合成设计需求。

    兜底：intake 老版本载荷只带 module/action/scope（无 intent），
    若不合成，architect spoke 按契约拒收空 intent，工单必然失败。
    """
    intent = str(intent or "").strip()
    if intent:
        return intent
    action = str(kwargs.get("action") or "").strip()
    scope = str(kwargs.get("scope") or "").strip()
    return " ".join(filter(None, [action, scope]))


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
            intent=_synthesize_intent(intent, kwargs),
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
