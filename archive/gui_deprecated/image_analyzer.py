"""
AKO_image_analyzer 子进程入口 — task_executor 调用。
stdin JSON → ako_image_analyzer.run() → stdout JSON
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ako_image_analyzer import run as adapter_run


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
        image_path=inputs.get("image_path", ""),
        _hub_output_dir=inputs.get("_hub_output_dir", ""),
        workflow_dir=inputs.get("workflow_dir"),
        entry_script=inputs.get("entry_script"),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
