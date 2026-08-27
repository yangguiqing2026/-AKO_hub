# -*- coding: utf-8 -*-
from __future__ import annotations
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil
import requests

HUB_HEARTBEAT_URL = "http://localhost:5000/heartbeat"
INTERVAL = 15

AKO_ROOT = Path(r"D:\AKO")
QC_DIR = AKO_ROOT / "AKO_qc_agent"
REGISTRY_DIR = AKO_ROOT / "AKO_registry_agent"
AUDIT_DIR = AKO_ROOT / "AKO_audit_agent"
GIT_PUSH_DIR = AKO_ROOT / "AKO_git_push_agent"

# registry agent uses its own venv python
REGISTRY_PY = REGISTRY_DIR / ".venv" / "Scripts" / "python.exe"
if not REGISTRY_PY.exists():
    REGISTRY_PY = Path(sys.executable)

# law agent: venv was broken (cp311 artifacts), repaired to Python 3.12
# use its own venv python (fallback to ako_agent_env)
LAW_DIR = AKO_ROOT / "AKO_law_agent"
# law venv fully repaired 2026-08-25: pyvenv.cfg fixed + all deps upgraded to cp312
LAW_PY = Path(r"D:\AKO\AKO_law_agent\.venv\Scripts\python.exe")

class AgentProc:
    def __init__(self, agent_id: str, cmd, cwd, probe):
        self.agent_id = agent_id
        self.cmd = cmd
        self.cwd = str(cwd)
        self.probe = probe
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def is_online(self) -> bool:
        if self.proc is None:
            return False
        return self.probe(self)

def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

def probe_qc(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:5001/health")

def probe_registry(ap: AgentProc) -> bool:
    return (
        ap.proc is not None
        and ap.proc.poll() is None
        and _http_ok("http://127.0.0.1:8010/ako/api/v1/registry/health")
    )

def probe_audit(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None

def probe_law(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:8001/health")

def post_heartbeat(agent_id: str, alive: bool) -> None:
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        payload = {
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "alive" if alive else "degraded",
            "cpu_percent": round(cpu, 2),
            "memory_mb": round(mem.used / (1024 * 1024), 1),
            "disk_percent": psutil.disk_usage("/").percent,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "last_task": "",
            "last_task_status": "",
            "response_time_ms": 0.0,
            "recent_tasks": [],
        }
        requests.post(HUB_HEARTBEAT_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[supervisor] heartbeat failed {agent_id}: {e}")

def main() -> None:
    agents = [
        AgentProc(
            "AKO_qc_agent",
            [str(Path(sys.executable)), "app.py", "--serve", "--port", "5001"],
            QC_DIR,
            probe_qc,
        ),
        AgentProc(
            "AKO_registry_agent",
            [str(REGISTRY_PY), "app.py", "serve", "--port", "8010"],
            REGISTRY_DIR,
            probe_registry,
        ),
        AgentProc(
            "AKO_audit_agent",
            [
                str(Path(sys.executable)),
                "src/main.py",
                "patrol",
                "--schedule-only",
                "--target",
                str(AUDIT_DIR),
            ],
            AUDIT_DIR,
            probe_audit,
        ),
        AgentProc(
            "AKO_law_agent",
            [str(LAW_PY), "main.py"],
            LAW_DIR,
            probe_law,
        ),
    ]

    # start real processes
    for ap in agents:
        try:
            ap.start()
            print(f"[supervisor] started {ap.agent_id} (pid={ap.proc.pid})")
        except Exception as e:
            print(f"[supervisor] start failed {ap.agent_id}: {e}")

    # git_push_agent: CLI only, one-shot runability check, keep offline
    try:
        r = subprocess.run(
            [str(Path(sys.executable)), "app.py", "--help"],
            cwd=str(GIT_PUSH_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
        git_push_runnable = r.returncode == 0
    except Exception:
        git_push_runnable = False
    print(f"[supervisor] AKO_git_push_agent runnable: {'OK(offline)' if git_push_runnable else 'FAIL'}")

    print(f"[supervisor] starting heartbeat loop (every {INTERVAL}s), Ctrl+C to stop...")
    try:
        while True:
            row = []
            for ap in agents:
                online = ap.is_online()
                if online:
                    post_heartbeat(ap.agent_id, alive=True)
                state = "ONLINE" if online else "OFFLINE"
                row.append(f"{ap.agent_id}={state}")
            row.append("AKO_git_push_agent=OFFLINE(cli)")
            print(f"[supervisor] {time.strftime('%H:%M:%S')} | " + " | ".join(row))
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        for ap in agents:
            if ap.proc and ap.proc.poll() is None:
                ap.proc.terminate()
        print("[supervisor] stopped all agents")

if __name__ == "__main__":
    main()
