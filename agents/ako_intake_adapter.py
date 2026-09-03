"""
AKO_hub_intake_agent — Hub 侧适配器

符合 SpokeAdapter 协议（core/spoke_protocol.py）：
run(intent, project_tag, _hub_output_dir, ...) -> {output_files, summary, error}
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

INTAKE_ROOT = Path(__file__).resolve().parent.parent.parent / "AKO_hub_intake_agent"
if str(INTAKE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTAKE_ROOT))


def _spoke() -> Any:
    """延迟构造 IntakeSpoke，避免 hub 启动时强依赖 intake。"""
    from ako_intake.adapters.spoke import IntakeSpoke
    from ako_intake.config import load_config

    return IntakeSpoke(load_config())


def run(
    intent: str = "",
    project_tag: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """SpokeAdapter.run 兼容入口。"""
    try:
        return _spoke().run(
            intent=intent,
            project_tag=project_tag,
            _hub_output_dir=_hub_output_dir,
            _hub_db_path=_hub_db_path,
            _hub_chroma_root=_hub_chroma_root,
            _hub_file_root=_hub_file_root,
            **kwargs,
        )
    except Exception as exc:
        return {
            "output_files": [],
            "summary": "intake 适配器调用失败",
            "error": f"{type(exc).__name__}: {exc}",
        }


def get_intake_status(session_id: str) -> Dict[str, Any]:
    """供 hub 看板查询 intake 会话状态。"""
    try:
        from ako_intake.config import load_config
        from ako_intake.db.session_store import SessionStore

        store = SessionStore(load_config().db.session_db)
        state = store.load(session_id)
        return state or {"error": "session not found", "session_id": session_id}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def accept_term_suggestion(term: str, module: str) -> Dict[str, Any]:
    """接收 intake 术语补录建议（写入事件流，由知识维护方处理）。"""
    try:
        from ako_intake.adapters.events import publish_event
        from ako_intake.config import load_config

        ok = publish_event(
            "term_suggestion",
            "AKO_hub_intake_agent",
            {"term": term, "module": module},
            hub_base_url=load_config().gateways.hub_base_url,
        )
        return {"status": "queued" if ok else "failed", "term": term, "module": module}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

