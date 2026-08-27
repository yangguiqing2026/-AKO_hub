"""
AKO Hub — AKO_geo 适配器
将仓库内 ako_geo 模块（内容营销×GEO×知识发酵）包装为 Hub Spoke，
供 TaskExecutor 子进程协议（stdin JSON → stdout JSON）调用。
"""
import json
from typing import Dict, Any

from ako_geo.spoke import run as geo_run


def run(
    intent: str = "",
    project_tag: str = "taoli",
    action: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。直接委托 ako_geo.spoke.run。"""
    return geo_run(
        intent=intent,
        project_tag=project_tag,
        _hub_output_dir=_hub_output_dir,
        _hub_db_path=_hub_db_path,
        _hub_chroma_root=_hub_chroma_root,
        _hub_file_root=_hub_file_root,
        **kwargs,
    )


if __name__ == "__main__":
    import sys

    # 子进程协议：TaskExecutor 通过 stdin 传入 JSON payload（非 TTY 时读取）
    payload: Dict[str, Any] = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
    inputs = payload.get("inputs", {}) or {}
    result = run(
        intent=payload.get("intent", inputs.get("intent", "")),
        project_tag=inputs.get("project_tag", "taoli"),
        **{k: v for k, v in inputs.items() if k not in ("intent", "project_tag")},
    )
    print(json.dumps(result, ensure_ascii=False))
