"""
AKO_reports FastAPI 入口 — task_executor 调用。
stdin JSON → ako_reports_adapter.run() → stdout JSON
也可独立启动 FastAPI 服务: python reports_app.py --serve
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ako_reports_adapter import run as adapter_run


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

    inputs = payload.get("inputs", {})

    result = adapter_run(
        _hub_output_dir=inputs.get("_hub_output_dir", ""),
        config=inputs.get("config"),
        project_dir=inputs.get("project_dir", ""),
        template_dir=inputs.get("template_dir", ""),
    )
    print(json.dumps(result, ensure_ascii=False))


def serve():
    """FastAPI 独立服务模式"""
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI(title="AKO Reports")

    @app.get("/health")
    def health():
        return {"status": "ok", "component": "reports", "checks": {}}

    @app.post("/invoke")
    async def invoke(payload: dict):
        inputs = payload.get("inputs", {})
        return adapter_run(
            _hub_output_dir=inputs.get("_hub_output_dir", ""),
            config=inputs.get("config"),
            project_dir=inputs.get("project_dir", ""),
            template_dir=inputs.get("template_dir", ""),
        )

    uvicorn.run(app, host="127.0.0.1", port=5001)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        handle_stdin()
