# -*- coding: utf-8 -*-
from __future__ import annotations
import os
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
# 2026-09-16：运维类 agent 此前不在任何启动/守护清单里 —— 集群巡检的日志
# 自 2026-08-25 起为空、心跳表 0 行，等于长期无人拉起（仅开机自启链里的
# 那些 agent 会被带起来）。下面纳入守护。
CLUSTER_GUARDIAN_DIR = AKO_ROOT / "AKO_cluster_guardian_agent"

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


def probe_cluster_guardian(ap: AgentProc) -> bool:
    """集群巡检无自开 HTTP：以其在 hub(:5000) 心跳的最近上报为存活判据。

    daemon 模式自带心跳客户端（interval 30s），判活窗口取 90s 留裕度。
    """
    if ap.proc is None or ap.proc.poll() is not None:
        return False
    try:
        with requests.get("http://127.0.0.1:5000/agents", timeout=5) as r:
            data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else []
        for a in agents:
            if a.get("agent_id") == "AKO_cluster_guardian_agent":
                try:
                    return int(a.get("seconds_ago", 999)) <= 90
                except (TypeError, ValueError):
                    return False
        return False
    except Exception:
        return False


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

# 2026-09-09 防复发：pid 锁文件（文件系统事实，绕开解释器 shim/进程枚举歧义）。
# 多触发源（计划任务 /run、开机、不同解释器）并存曾致多 supervisor 各拉整套
# agent → 每 agent 双/多实例抢端口。锁文件持存活 pid 即视为另一实例在位。
SUPERVISOR_LOCK = Path(__file__).resolve().parent.parent / "logs" / "supervisor.lck"


def _is_live_supervisor(pid: int) -> bool:
    """pid 存活且确为 agent_supervisor（防 pid 复用误判）。"""
    try:
        p = psutil.Process(pid)
        cl = p.cmdline() or []
        return any("agent_supervisor.py" in str(c) for c in cl)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


# 2026-09-11 补：原子独占创建。
#
# 2026-09-09 的 pid 锁已能挡住「顺序启动」的第二实例，但挡不住「同时启动」——
# 原实现先 exists/read 判断、再 write_text，两个进程可同时读到陈旧或空缺状态
# 并双双写入，双双返回 True。实测本机因此并存两个 supervisor（PID 9748/15112，
# 分别由计划任务与手动两条入口拉起），各拉一套 10 个 agent → 每个 agent 双实例
# 抢同一端口（Windows 允许重复 bind 不报错，故障静默）。
#
# 现以 O_CREAT|O_EXCL 为唯一裁决点：读到的锁只用于判断「是否该清除陈旧锁」，
# 绝不作为持锁依据。
LOCK_ACQUIRE_ATTEMPTS = 5


def _try_create_lock() -> bool:
    """原子独占创建锁文件并写入本进程 pid；已被占用返回 False。"""
    SUPERVISOR_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(SUPERVISOR_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _read_lock_pid() -> int | None:
    """读锁内 pid；文件缺失或内容损坏返回 None。"""
    try:
        return int(SUPERVISOR_LOCK.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _acquire_singleton() -> bool:
    """接管 pid 锁；另一活 supervisor 在位则返回 False。"""
    for _ in range(LOCK_ACQUIRE_ATTEMPTS):
        if _try_create_lock():
            return True
        old = _read_lock_pid()
        if old is not None and _is_live_supervisor(old):
            return False  # 另一活实例在位，让位
        # 陈旧锁（pid 已死 / 非 supervisor / 内容损坏）：清除后重试。
        # 并发下可能已被对手清掉 → FileNotFoundError 属正常，继续抢。
        try:
            SUPERVISOR_LOCK.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False  # 不可恢复错误：保守让位，避免双实例
    return False


def _release_singleton() -> None:
    """仅当锁属于本进程时释放（防误清活实例的锁 → 引出第三个实例）。"""
    if _read_lock_pid() == os.getpid():
        try:
            SUPERVISOR_LOCK.unlink()
        except OSError:
            pass


def _agent_already_running(ap: AgentProc) -> bool:
    """该 agent 是否已有实例在跑（同命令尾部 + 同 cwd 的 python 进程，排除自己）。

    2026-09-09 防复发：第二 supervisor 或重复 start 时不再重复拉起同一 agent。
    须带 cwd 判定：多 agent 命令尾部同为 "app.py"（quote/guardian），且 hub
    (pythonw app.py) 也在跑——只比尾部会把 hub 误判为 quote 已在线而 skip。
    """
    if len(ap.cmd) < 2:
        return False
    tail = " ".join(ap.cmd[1:])
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info.get("pid") == me:
                continue
            name = (p.info.get("name") or "").lower()
            if not name.startswith("python"):
                continue
            cl = p.info.get("cmdline") or []
            if len(cl) <= 1 or " ".join(cl[1:]) != tail:
                continue
            try:
                if str(p.cwd()).lower() == str(ap.cwd).lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # cwd 不可读：仅尾部匹配时要求非 pythonw（排除 hub 误判）
                if not name.endswith("pythonw"):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def main() -> None:
    if not _acquire_singleton():
        print("[supervisor] 另一 supervisor 实例已在运行（pid 锁） - 退出（防双实例）")
        return
    try:
        _main_loop()
    finally:
        _release_singleton()


def _main_loop() -> None:
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
        AgentProc(
            "AKO_cluster_guardian_agent",
            [str(Path(sys.executable)), "main.py", "--mode", "daemon"],
            CLUSTER_GUARDIAN_DIR,
            probe_cluster_guardian,
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

    # start real processes（2026-09-09：已在线 agent 跳过，防双实例）
    for ap in agents:
        try:
            if _agent_already_running(ap):
                print(f"[supervisor] {ap.agent_id} 已有实例在跑 - skip")
                ap.proc = None  # 不接管既有实例（探针走 HTTP/进程，不依赖 proc 句柄）
                continue
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
