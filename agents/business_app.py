"""
AKO_business FastAPI 入口 — task_executor 调用。
stdin JSON → ako_business_adapter.run() → stdout JSON
也可独立启动 FastAPI 服务: python business_app.py --serve
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ako_business_adapter import run as adapter_run


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
        project_tag=inputs.get("project_tag", "taoli"),
        project_id=inputs.get("project_id", ""),
        action=inputs.get("action", ""),
        _hub_output_dir=inputs.get("_hub_output_dir", ""),
    )
    print(json.dumps(result, ensure_ascii=False))


def serve():
    """FastAPI 独立服务模式"""
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI(title="AKO Business")

    @app.get("/health")
    def health():
        return {"status": "ok", "component": "business", "checks": {}}

    @app.post("/invoke")
    async def invoke(payload: dict):
        intent = payload.get("intent", "")
        inputs = payload.get("inputs", {})
        return adapter_run(
            intent=intent,
            project_tag=inputs.get("project_tag", "taoli"),
            project_id=inputs.get("project_id", ""),
            action=inputs.get("action", ""),
            _hub_output_dir=inputs.get("_hub_output_dir", ""),
        )

    uvicorn.run(app, host="127.0.0.1", port=5002)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        handle_stdin()
