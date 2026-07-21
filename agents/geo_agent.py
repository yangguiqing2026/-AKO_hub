"""
AKO_geo 子进程入口 — task_executor 调用。
stdin JSON → ako_geo.spoke.run() → stdout JSON
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ako_geo.spoke import run as adapter_run


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"status": "failed", "error": "无输入"}, ensure_ascii=False))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "failed", "error": f"JSON解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    intent = payload.get("intent", "")
    inputs = payload.get("inputs", {})

    result = adapter_run(
        intent=intent,
        project_tag=inputs.get("project_tag", "taoli"),
        _hub_output_dir=inputs.get("_hub_output_dir", ""),
        _hub_db_path=inputs.get("_hub_db_path", ""),
        _hub_chroma_root=inputs.get("_hub_chroma_root", ""),
        _hub_file_root=inputs.get("_hub_file_root", ""),
        platform=inputs.get("platform", "zhihu"),
        sources=inputs.get("sources", []),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
