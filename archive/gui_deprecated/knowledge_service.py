"""
AKO_knowledge 服务入口 — task_executor 子进程调用。
stdin JSON → ako_knowledge_adapter.run() → stdout JSON
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ako_knowledge_adapter import run as adapter_run


def handle_stdin():
    """task_executor 子进程模式：stdin JSON → stdout JSON"""
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
        action=inputs.get("action", "health"),
        _hub_output_dir=inputs.get("_hub_output_dir", ""),
        kb_id=inputs.get("kb_id", ""),
        query=inputs.get("query", ""),
        n_results=inputs.get("n_results", 5),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    handle_stdin()
