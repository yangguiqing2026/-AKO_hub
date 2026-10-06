# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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

# 2026-10-05（WO-HAI-20261005-005）：guardian 功能级探针参数
# N=26h：值守巡检 24h 周期（每日 05:30）+ 钩子窗口（00:30~04:00），
#        最长合法产出间隔 ≈20.5h；取 24h+2h 裕度。论证详见验收报告。
GUARDIAN_FRESHNESS_HOURS = 26
# 冷启动宽限：进程新起 ≤120 分钟且无任何产出时视为"未就绪"（放行，不判死）
GUARDIAN_COLD_START_MINUTES = 120

# 2026-10-06（WO-HAI-20261006-009）：supervisor 告警卫生三件套
# 铁律1：静音与 guardian 巡检告警同口径——同 Agent+同异常类型，静默 180 分钟，期满重报
ALERT_SILENCE_MINUTES = 180
# 铁律2：告警判定/发送结果 append-only 落盘
SUPERVISOR_ALERT_LOG = Path(__file__).resolve().parent.parent / "logs" / "supervisor_alerts.jsonl"
# 铁律1 配套：静音状态持久化（跨 supervisor 重启持续生效）
SUPERVISOR_ALERT_SILENCE_FILE = (
    Path(__file__).resolve().parent.parent / "logs" / "supervisor_alert_silence.json")

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
    def __init__(self, agent_id: str, cmd, cwd, probe, capture_log: Path | None = None):
        self.agent_id = agent_id
        self.cmd = cmd
        self.cwd = str(cwd)
        self.probe = probe
        self.proc: subprocess.Popen | None = None
        self.offline_streak: int = 0
        self.restarts: list[float] = []  # 重启时间戳（用于每小时限流）
        # 2026-10-05（WO-005）：温启动"接管"标记——既有实例不由本进程 Popen 持有
        # （旧代码此情形下 probe 直接 False → 会触发双实例式重启，属部署安全隐患）
        self.adopted: bool = False
        # 可选：子进程 stdout/stderr 落盘（DEVNULL 曾使停摆事故零取证）
        self.capture_log: Path | None = Path(capture_log) if capture_log else None

    def start(self) -> None:
        out = subprocess.DEVNULL
        err = subprocess.DEVNULL
        self._capture_fh = None
        if self.capture_log is not None:
            try:
                self.capture_log.parent.mkdir(parents=True, exist_ok=True)
                # 简易轮转：>5MB 时滚动到 .1（保留一份）
                if self.capture_log.exists() and self.capture_log.stat().st_size > 5_242_880:
                    bak = self.capture_log.with_suffix(self.capture_log.suffix + ".1")
                    try:
                        if bak.exists():
                            bak.unlink()
                        self.capture_log.rename(bak)
                    except OSError:
                        pass
                self._capture_fh = open(self.capture_log, "a", encoding="utf-8")
                out = self._capture_fh
                err = self._capture_fh
            except OSError:
                out = subprocess.DEVNULL
                err = subprocess.DEVNULL
        # WO-008 P1-7：强制子进程无缓冲（等效 python -u）——PYTHONUNBUFFERED 沿启动链
        # 传递到基础解释器，消除 stdout 块缓冲致 guardian_daemon.log 存活期恒空；
        # 不改动 self.cmd 形态，避免影响 _running_pids 的命令尾部匹配。
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, stdout=out, stderr=err, env=env)

    def is_process_alive(self) -> bool:
        """进程存活（句柄存活，或由既有实例匹配器复核）。

        2026-10-05（WO-007）修复：原实现在 proc 句柄"存在但已死"时直接返回 False，
        匹配器被永久跳过——"句柄死 + adopted=False"（restart().start() 拉起的子
        进程退出/被清除后的残留态）下，即使存在活着的既有实例也被永久判死，
        状态行恒 OFFLINE（WO-006 §四·观察4 矛盾根因）。现统一回退匹配器复核。
        """
        if self.proc is not None and self.proc.poll() is None:
            return True
        return _agent_already_running(self)

    def restart(self, now: float) -> bool:
        """受限自动重启：每小时最多 MAX_RESTARTS_PER_HOUR 次。返回是否执行了重启。"""
        self.restarts = [t for t in self.restarts if now - t < 3600]
        if len(self.restarts) >= MAX_RESTARTS_PER_HOUR:
            # WO-008 P1-5：熔断拒绝可见化（被拒对象 + 剩余冷却时间；此前为静默 return）
            cooldown = min(t + 3600 - now for t in self.restarts)
            print(f"[supervisor] restart throttled {self.agent_id}: "
                  f"近 1 小时已重启 {len(self.restarts)}/{MAX_RESTARTS_PER_HOUR} 次，"
                  f"剩余冷却 {cooldown:.0f}s"
                  f"（最早 {time.strftime('%H:%M:%S', time.localtime(min(self.restarts) + 3600))} 可重试）")
            return False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        elif self.adopted:
            # 接管态重启：按匹配器定位既有实例并终止（防双实例），再全新拉起
            for pid in _running_pids(self):
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=10)
                    except psutil.TimeoutExpired:
                        p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.adopted = False
        self.start()
        self.restarts.append(now)
        self.offline_streak = 0
        return True

    def is_online(self) -> bool:
        if not self.is_process_alive():
            return False
        return self.probe(self)

def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

def probe_qc(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:5001/health")

def probe_registry(ap: AgentProc) -> bool:
    return (
        ap.is_process_alive()
        and _http_ok("http://127.0.0.1:5024/ako/api/v1/registry/health")
    )

def probe_audit(ap: AgentProc) -> bool:
    return ap.is_process_alive()

def probe_law(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:8001/health")

def probe_knowledge(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:8000/docs")

def probe_guardian(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:5033/health")

def probe_web_consult(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:7863/docs")

def probe_identity(ap: AgentProc) -> bool:
    return ap.is_process_alive() and _http_ok("http://127.0.0.1:5025/health")

def probe_monitor(ap: AgentProc) -> bool:
    return ap.is_process_alive()


def probe_cluster_guardian(ap: AgentProc) -> bool:
    """集群巡检功能级探针（WO-HAI-20261005-005 方案A，审签批准）：

    双重证据 = ①进程存活 ②hub 心跳 ≤90s ③**近期产出新鲜度**（≤26h）。

    2026-10-05 停摆事故教训（根因分析见验收报告）：
    - 本文件心跳循环会「代发」各 agent 心跳（post_heartbeat），单看 hub 心跳
      是循环自证——旧实例功能停摆 7 天仍显示 ONLINE 的直接原因；
    - 产出新鲜度（output/patrol、output/audit、output/guardian_run）由守护进程
      自身写入，不可自证，是本探针的决定性证据。

    N=26h 论证：值守巡检 24h 周期（每日 05:30）+ 钩子 00:30~04:00，
    最长合法产出间隔 ≈20.5h；取 26h（24h+2h 裕度）。
    冷启动宽限：进程新起 ≤120 分钟且尚无任何产出时视为未就绪（放行）。
    """
    if not ap.is_process_alive():
        return False
    hb_ok = _guardian_hub_heartbeat_ok()
    age_hours = _guardian_output_age_hours()
    proc_age_min = _proc_age_minutes(ap)
    return _functional_ok(hb_ok, age_hours, proc_age_min)


def _guardian_hub_heartbeat_ok(timeout: float = 5.0) -> bool:
    """hub 心跳 ≤90s（辅助证据；注意其可能由 supervisor 代发）。"""
    try:
        r = requests.get("http://127.0.0.1:5000/agents", timeout=timeout)
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


def _newest_output_age_hours(base_dir: Path) -> float | None:
    """目录下三类产出（patrol/audit/run）最新文件的年龄（小时）；无产出返回 None。

    纯函数（可单测）：产出新鲜度是本探针不可自证的独立证据。
    """
    newest = 0.0
    for pattern in ("output/patrol/guardian_patrol_*.json",
                    "output/audit/guardian_audit_*.jsonl",
                    "output/guardian_run_*.json"):
        for f in base_dir.glob(pattern):
            try:
                m = f.stat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                continue
    if newest <= 0:
        return None
    return (time.time() - newest) / 3600.0


def _guardian_output_age_hours() -> float | None:
    """guardian 最近产出距今小时数（多源取最新）；无任何产出返回 None。"""
    return _newest_output_age_hours(CLUSTER_GUARDIAN_DIR)


def _proc_age_minutes(ap: AgentProc) -> float:
    """进程已运行分钟数；不可得时返回大值（按已就绪处理）。"""
    try:
        if ap.proc is not None:
            return (time.time() - psutil.Process(ap.proc.pid).create_time()) / 60.0
        pids = _running_pids(ap)
        if pids:
            return (time.time() - psutil.Process(pids[0]).create_time()) / 60.0
    except Exception:
        pass
    return 9999.0


def _functional_ok(hb_ok: bool, age_hours: float | None, proc_age_minutes: float) -> bool:
    """功能级判定（纯函数，便于单测）：
    产出新鲜=决定性证据；无产出时按冷启动宽限（≤120min 放行）。心跳为辅助。"""
    if age_hours is not None:
        fresh = age_hours <= GUARDIAN_FRESHNESS_HOURS
    else:
        fresh = proc_age_minutes < GUARDIAN_COLD_START_MINUTES
    return hb_ok and fresh


def _format_alert_result(result: dict) -> str:
    """告警结果单行格式化（WO-008 P1-6：含 subject，供【测试】前缀实证与运维核对）。"""
    return (f"[supervisor] guardian 功能死告警: mode={result.get('mode')} "
            f"sent={result.get('sent')} subject={result.get('subject', '')} "
            f"err={result.get('error', '')}")


class AlertSilenceLedger:
    """告警静音账本（WO-009 铁律1）：同 Agent+同异常类型，静默 180 分钟，期满重报。

    与 guardian 巡检告警同口径（netwatch AlertState.should_send 语义：放行即记时，
    尝试即算，失败不风暴重试）；状态落盘 JSON，跨实例/supervisor 重启持续生效。
    """

    def __init__(self, path: Path | None = None, window_minutes: int | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self.path = Path(path) if path is not None else SUPERVISOR_ALERT_SILENCE_FILE
        self.window_seconds = float((window_minutes if window_minutes is not None
                                     else ALERT_SILENCE_MINUTES) * 60)
        self.clock = clock or time.time
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                entries = data.get("entries") if isinstance(data, dict) else None
                if isinstance(entries, dict):
                    self._entries = entries
        except Exception as e:  # 状态损坏不得阻断告警（降级为空账本）
            print(f"[supervisor] 静音状态读取失败（降级为空账本）: {e}")
            self._entries = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"version": 1, "entries": self._entries},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception as e:  # 落盘失败仅降级为内存生效，不阻断监督
            print(f"[supervisor] 静音状态落盘失败（仅内存生效）: {e}")

    def allow(self, event_key: str) -> tuple[bool, float]:
        """判定并记账：返回 (是否放行, 被静默时剩余秒数)。放行即持久化记时。"""
        now = self.clock()
        state = self._entries.get(event_key)
        if state is not None:
            elapsed = now - float(state.get("last_sent", 0.0))
            if elapsed < self.window_seconds:
                return False, self.window_seconds - elapsed
            state["last_sent"] = now
            state["count"] = int(state.get("count", 0)) + 1
        else:
            self._entries[event_key] = {"first_alert": now, "last_sent": now, "count": 1}
        self._save()
        return True, 0.0


_ALERT_LEDGER: AlertSilenceLedger | None = None


def _get_alert_ledger() -> AlertSilenceLedger:
    """生产用静音账本单例（测试经参数注入替身，不触本函数）。"""
    global _ALERT_LEDGER
    if _ALERT_LEDGER is None:
        _ALERT_LEDGER = AlertSilenceLedger()
    return _ALERT_LEDGER


def _append_supervisor_alert_log(record: dict, path: Path | None = None) -> bool:
    """告警判定/发送结果 append-only 落盘（WO-009 铁律2）。失败仅告警不阻断。"""
    target = Path(path) if path is not None else SUPERVISOR_ALERT_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[supervisor] 告警留痕写入失败（不阻断监督）: {e}")
        return False


def _alert_recipient(dispatcher: Any) -> str:
    """从派发器提取收件人（不可得时返回空串，仅影响留痕字段）。"""
    try:
        return str(getattr(getattr(dispatcher, "notifier", None), "email", "") or "")
    except Exception:
        return ""


def _ensure_guardian_import_path() -> None:
    """将 cluster_guardian 目录加入 sys.path（guardian 模块为只读依赖，不改动）。"""
    gdir = str(CLUSTER_GUARDIAN_DIR)
    if gdir not in sys.path:
        sys.path.insert(0, gdir)


def _build_functional_down_dispatcher() -> Any:
    """构建真实告警派发器（唯一真实通道出口；凭据经 netwatch secrets.env 同源注入）。

    WO-009：mock 实测经 dispatcher_factory 注入替身，绝不调用本函数（零真实外发）。
    """
    secrets_path = AKO_ROOT / "AKO_netwatch_agent" / "secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    _ensure_guardian_import_path()
    from src.core.patrol import load_active_duty_config  # type: ignore
    from src.core.alert_dispatcher import AlertDispatcher  # type: ignore

    return AlertDispatcher(load_active_duty_config())


def _force_line_buffered_stdout(stream: object | None = None) -> bool:
    """自身 stdout 行缓冲（WO-009 铁律3，等效 PYTHONUNBUFFERED；对任意启动路径兜底）。"""
    target = stream if stream is not None else sys.stdout
    try:
        reconfigure = getattr(target, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(line_buffering=True)
            return True
    except Exception:
        pass
    return False


def _notify_guardian_functional_down(evidence: str, *, ledger: AlertSilenceLedger | None = None,
                                     dispatcher_factory: Callable[[], Any] | None = None,
                                     alert_log: Path | None = None) -> None:
    """探针判死后告警出口（铁律5）：经 guardian 告警派发器（netwatch 通道）。

    2026-10-06（WO-009）：
    - 静音（铁律1）：同 Agent+同异常类型（本路径固定 AKO_cluster_guardian_agent:DOWN），
      180 分钟内仅首报外发、期满重报，状态跨重启持久化——风暴不再依赖根因消失；
    - 留痕（铁律2）：每次判定（实发/静默/失败）append 一条 JSONL；
    - 禁止新建 SMTP 通道：仍复用既有派发链（本函数不引入任何 SMTP 配置）。
    测试注入 ledger/dispatcher_factory/alert_log 时为全程 mock，零真实外发。
    """
    led = ledger if ledger is not None else _get_alert_ledger()
    event_key = "AKO_cluster_guardian_agent:DOWN"
    allowed, remaining = led.allow(event_key)
    base = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "caller": "supervisor_watchdog",
        "agent_id": "AKO_cluster_guardian_agent",
        "verdict": "DOWN",
        "event_key": event_key,
        "evidence": evidence,
    }
    if not allowed:
        _append_supervisor_alert_log(
            {**base, "mode": "suppressed_local", "sent": False, "recipient": "", "subject": "",
             "error": f"静默窗口内（{ALERT_SILENCE_MINUTES} 分钟），剩余 {remaining:.0f}s"},
            alert_log)
        print(f"[supervisor] 功能死告警静默：{event_key} 近 {ALERT_SILENCE_MINUTES} 分钟内已报警"
              f"（剩余 {remaining:.0f}s），本次不外发")
        return
    dispatcher = None
    result: dict = {}
    try:
        _ensure_guardian_import_path()
        build = dispatcher_factory or _build_functional_down_dispatcher
        dispatcher = build()
        from src.core.health_probe import AgentHealth, CheckOutcome, now_beijing  # type: ignore

        health = AgentHealth(
            agent_id="AKO_cluster_guardian_agent",
            verdict="DOWN",
            checks=[CheckOutcome("supervisor_functional_probe", "fail", evidence)],
            checked_at=now_beijing().isoformat(),
        )
        decision = {
            "agent_id": "AKO_cluster_guardian_agent",
            "verdict": "DOWN",
            "action": "alert_only",
            "reason": "supervisor 功能级探针判死（心跳+产出双证据），进入受限重启机制",
        }
        result = dispatcher.dispatch(health, decision, "supervisor_watchdog", dry_run=False)
    except Exception as e:
        result = {"sent": False, "mode": "error", "subject": "", "error": f"{type(e).__name__}: {e}"}
        print(f"[supervisor] guardian 功能死告警发送失败（仅记录，不阻断监督）: {e}")
    _append_supervisor_alert_log(
        {**base, "mode": result.get("mode", ""), "sent": bool(result.get("sent")),
         "recipient": _alert_recipient(dispatcher), "subject": result.get("subject", ""),
         "error": result.get("error", "")},
        alert_log)
    if result.get("mode") != "error":
        print(_format_alert_result(result))


def probe_quote(ap: AgentProc) -> bool:
    """quote 服务无自开 HTTP：以其在 hub(:5000) 心跳 DB 的最近上报为存活判据。

    2026-09-09：此前查 registry(5024) 自注册；quote 心跳已改指 hub :5000
    （registry_url 见 quote config.yaml），5024 不再有 quote 上报，继续查
    5024 会误判死亡触发反复重启。hub 收心跳即登记 agents_registry。
    """
    if not ap.is_process_alive():
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


def _running_pids(ap: AgentProc) -> list:
    """该 agent 的既有实例 pid 列表（同命令尾部 + 同 cwd 的 python 进程，排除自己）。

    2026-09-09 防复发：第二 supervisor 或重复 start 时不再重复拉起同一 agent。
    须带 cwd 判定：多 agent 命令尾部同为 "app.py"（quote/guardian），且 hub
    (pythonw app.py) 也在跑——只比尾部会把 hub 误判为 quote 已在线而 skip。
    2026-10-05（WO-005）：拆出 pid 列表供"接管态重启"使用。
    """
    if len(ap.cmd) < 2:
        return []
    tail = " ".join(ap.cmd[1:])
    me = os.getpid()
    pids = []
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
                    pids.append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # cwd 不可读：仅尾部匹配时要求非 pythonw（排除 hub 误判）
                if not name.endswith("pythonw"):
                    pids.append(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _agent_already_running(ap: AgentProc) -> bool:
    """该 agent 是否已有实例在跑。"""
    return bool(_running_pids(ap))


def main() -> None:
    _force_line_buffered_stdout()  # WO-009 铁律3：自身日志存活期实时有字（等效 -u）
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
            # WO-005：daemon stdout/stderr 落盘（DEVNULL 曾使停摆事故零取证）
            capture_log=CLUSTER_GUARDIAN_DIR / "logs" / "guardian_daemon.log",
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
                print(f"[supervisor] {ap.agent_id} 已有实例在跑 - 接管（adopted）")
                ap.proc = None
                ap.adopted = True  # 2026-10-05（WO-005）：接管态参与探针与重启，防温启动双实例
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
                            # WO-005 铁律5：guardian 功能死 → 经获批告警出口（guardian 派发器/netwatch 通道）
                            if ap.agent_id == "AKO_cluster_guardian_agent":
                                age = _guardian_output_age_hours()
                                _notify_guardian_functional_down(
                                    f"probe fail x{ap.offline_streak}; "
                                    f"output_age_hours={round(age, 2) if age is not None else '无产出'}")
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
