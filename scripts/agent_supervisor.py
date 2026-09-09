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
KNOWLEDGE_DIR = AKO_ROOT / "AKO_knowledge"
GUARDIAN_DIR = AKO_ROOT / "AKO_guardian_agent"
WEB_CONSULT_DIR = AKO_ROOT / "AKO_web_consult_agent"
IDENTITY_DIR = AKO_ROOT / "AKO_identity_service"
MONITOR_DIR = AKO_ROOT / "AKO_monitor_agent"
QUOTE_DIR = AKO_ROOT / "AKO_quote_agent"

# 自动重启约束：连续 OFFLINE_RESTART_AFTER 次判定后重启，每小时最多 MAX_RESTARTS_PER_HOUR 次
OFFLINE_RESTART_AFTER = 2
MAX_RESTARTS_PER_HOUR = 3

# registry agent uses its own venv python
REGISTRY_PY = REGISTRY_DIR / ".venv" / "Scripts" / "python.exe"
if not REGISTRY_PY.exists():
    REGISTRY_PY = Path(sys.executable)

# law agent: venv was broken (cp311 artifacts), repaired to Python 3.12
# use its own venv python (fallback to ako_agent_env)
LAW_DIR = AKO_ROOT / "AKO_law_agent"
# law venv fully repaired 2026-08-25: pyvenv.cfg fixed + all deps upgraded to cp312
LAW_PY = Path(r"D:\AKO\AKO_law_agent\.venv\Scripts\python.exe")

# knowledge uses its own venv (python 3.9+), fallback shared env
KNOWLEDGE_PY = KNOWLEDGE_DIR / ".venv" / "Scripts" / "python.exe"
if not KNOWLEDGE_PY.exists():
    KNOWLEDGE_PY = Path(sys.executable)

# guardian uses its own venv
GUARDIAN_PY = GUARDIAN_DIR / ".venv" / "Scripts" / "python.exe"
if not GUARDIAN_PY.exists():
    GUARDIAN_PY = Path(sys.executable)


class AgentProc:
    def __init__(self, agent_id: str, cmd, cwd, probe):
        self.agent_id = agent_id
        self.cmd = cmd
        self.cwd = str(cwd)
        self.probe = probe
        self.proc: subprocess.Popen | None = None
        self.offline_streak: int = 0
        self.restarts: list[float] = []  # 重启时间戳（用于每小时限流）

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def restart(self, now: float) -> bool:
        """受限自动重启：每小时最多 MAX_RESTARTS_PER_HOUR 次。返回是否执行了重启。"""
        self.restarts = [t for t in self.restarts if now - t < 3600]
        if len(self.restarts) >= MAX_RESTARTS_PER_HOUR:
            return False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.start()
        self.restarts.append(now)
        self.offline_streak = 0
        return True

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
        and _http_ok("http://127.0.0.1:5024/ako/api/v1/registry/health")
    )

def probe_audit(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None

def probe_law(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:8001/health")

def probe_knowledge(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:8000/docs")

def probe_guardian(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:5033/health")

def probe_web_consult(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:7863/docs")

def probe_identity(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None and _http_ok("http://127.0.0.1:5025/health")

def probe_monitor(ap: AgentProc) -> bool:
    return ap.proc is not None and ap.proc.poll() is None


def probe_quote(ap: AgentProc) -> bool:
    """quote 服务无自开 HTTP：以其在 hub(:5000) 心跳 DB 的最近上报为存活判据。

    2026-09-09：此前查 registry(5024) 自注册；quote 心跳已改指 hub :5000
    （registry_url 见 quote config.yaml），5024 不再有 quote 上报，继续查
    5024 会误判死亡触发反复重启。hub 收心跳即登记 agents_registry。
    """
    if ap.proc is None or ap.proc.poll() is not None:
        return False
    try:
        with requests.get("http://127.0.0.1:5000/agents", timeout=5) as r:
            data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else []
        for a in agents:
            if a.get("agent_id") == "AKO_quote_agent":
                # 最近心跳 ≤ 90s 判定存活（quote 心跳间隔 60s + 裕度）
                try:
                    return int(a.get("seconds_ago", 999)) <= 90
                except (TypeError, ValueError):
                    return False
        return False
    except Exception:
        return False

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
            [str(REGISTRY_PY), "app.py", "serve", "--port", "5024"],
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
        AgentProc(
            "AKO_knowledge",
            [str(KNOWLEDGE_PY), "-m", "uvicorn", "knowledge_service:app",
             "--host", "127.0.0.1", "--port", "8000"],
            KNOWLEDGE_DIR,
            probe_knowledge,
        ),
        AgentProc(
            "AKO_guardian_agent",
            [str(GUARDIAN_PY), "app.py"],
            GUARDIAN_DIR,
            probe_guardian,
        ),
        AgentProc(
            "AKO_web_consult_agent",
            [str(Path(sys.executable)), "-m", "uvicorn", "src.main:app",
             "--host", "127.0.0.1", "--port", "7863"],
            WEB_CONSULT_DIR,
            probe_web_consult,
        ),
        AgentProc(
            "AKO_identity_service",
            [str(Path(sys.executable)), "app.py", "--port", "5025"],
            IDENTITY_DIR,
            probe_identity,
        ),
        AgentProc(
            "AKO_monitor_agent",
            [str(Path(sys.executable)), "main.py"],
            MONITOR_DIR,
            probe_monitor,
        ),
        # 2026-09-03 批2 收尾：quote 纳入 supervisor（第 10 服务）。
        # quote app.py 主流程含 SDK 自注册+心跳（无自开 HTTP），以 registry 注册为探针。
        # 注：supervisor 当前未在本机运行（9 服务心跳由各自 SDK 自嵌上报）；
        # 本条目为配置预备，宿主启用 supervisor 时生效。
        AgentProc(
            "AKO_quote_agent",
            [str(Path(sys.executable)), "app.py"],
            QUOTE_DIR,
            probe_quote,
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
            now = time.time()
            for ap in agents:
                online = ap.is_online()
                if online:
                    ap.offline_streak = 0
                    post_heartbeat(ap.agent_id, alive=True)
                else:
                    ap.offline_streak += 1
                    if ap.offline_streak >= OFFLINE_RESTART_AFTER:
                        restarted = ap.restart(now)
                        if restarted:
                            print(f"[supervisor] auto-restart {ap.agent_id} (offline x{ap.offline_streak})")
                            online = True
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
