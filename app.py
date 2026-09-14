#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — AKO_hub 总调度中枢主服务。

职责：
1. 启动 HTTP 层（hub_http_server，默认端口 8080）：Agent 注册、事件订阅。
2. 启动心跳接收服务（heartbeat_server，默认端口 5000）：接收各 Agent 心跳。
3. 保持前台运行，Ctrl+C 优雅退出。

用法：
    python app.py
    python app.py --http-port 8080 --heartbeat-port 5000
    python start.py serve
"""

import os
os.environ["PYTHONIOENCODING"] = "utf-8"
import argparse
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# 单实例锁（2026-09-10 补）
#
# 故障模式：**Windows 允许两个进程 bind 同一端口而不报错**（不同于 Linux 的
# EADDRINUSE）。重复启动 hub 不会失败，而是静默形成「双 hub + 双 pending_worker」，
# 两个 worker 线程竞争消费同一 task_queue。
#
# 后果不仅是资源浪费：同一批代码修复，旧实例用旧模块执行、新实例用新模块执行，
# 派单被哪个实例认领不可预测 —— 2026-09-10 实际发生：三次立法派单被未重启的旧
# hub 认领，代码修复「看似无效」，排查耗时数小时。
#
# 实现沿用 scripts/agent_supervisor.py 的 pid 锁（2026-09-09 防复发，同因）：
# 以文件系统事实为准，绕开解释器 shim / 进程枚举歧义；并校验 pid 确为 hub 进程，
# 防 pid 复用误判。持锁进程死亡后，锁可被下次启动自动接管。
# =============================================================================

HUB_DIR = Path(__file__).resolve().parent
HUB_LOCK = HUB_DIR / "logs" / "hub.lck"


def _cwd_is_hub(proc) -> bool:
    """进程工作目录是否就是 hub 目录（Windows 路径大小写不敏感）。"""
    try:
        return os.path.normcase(os.path.abspath(proc.cwd())) == os.path.normcase(str(HUB_DIR))
    except Exception:
        return False


def _is_live_hub(pid: int) -> bool:
    """pid 存活且确为 AKO_hub 进程（防 pid 复用误判）。

    两条判定路径，满足其一即可（2026-09-14 补第二条）：

    1. 命令行含 "AKO_hub" —— 以绝对路径启动的形态；
    2. 进程工作目录即 hub 目录 —— **进程 CommandLine 不含工作目录**，而 intake
       侧 hub_bootstrap.launch_hub() 正是以 cwd=HUB_DIR + 相对 "app.py" 拉起，
       命令行只有 "pythonw.exe app.py"。仅凭命令行判定会把这种实例误判为已死，
       新实例于是接管锁并与旧实例并存（Windows 允许同端口双 bind，故障静默）。
    """
    try:
        import psutil
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline() or [])
        if "app.py" not in cmdline:
            return False
        if "AKO_hub" in cmdline or "ako_hub" in cmdline.lower():
            return True
        return _cwd_is_hub(proc)
    except Exception:
        return False


def acquire_singleton() -> bool:
    """接管 hub 单实例锁；另一活 hub 在位则返回 False。"""
    try:
        HUB_LOCK.parent.mkdir(parents=True, exist_ok=True)
        if HUB_LOCK.exists():
            try:
                old = int(HUB_LOCK.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                old = -1          # 锁文件损坏/不可读 → 视为无锁，继续接管
            if old > 0 and _is_live_hub(old):
                logger.error(
                    f"已有 AKO_hub 实例在运行（PID {old}），本次启动终止。"
                    f"如需强制接管：先停止该进程，锁将自动失效（或删除 {HUB_LOCK}）。"
                )
                return False
        HUB_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError as exc:
        # 锁不可写不应阻断启动（如只读文件系统），但须显式告警
        logger.warning(f"单实例锁不可用（{exc}），本次启动未加锁")
        return True


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="AKO_hub 主服务（HTTP 层 + 心跳接收）"
    )
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP 层端口")
    parser.add_argument("--heartbeat-port", type=int, default=5000, help="心跳接收端口")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    )

    # 单实例锁：防止双 hub 并存（Windows 端口可重复 bind，不会自动失败）
    if not acquire_singleton():
        raise SystemExit(1)

    # 延迟导入，避免启动阶段因依赖缺失而失败
    from hub_http_server import run as run_http_layer
    from heartbeat.heartbeat_server import run as run_heartbeat, init_heartbeat_db

    logger.info("AKO_hub 主服务启动中...")

    # 初始化心跳数据库（幂等）
    init_heartbeat_db()

    # 线程化启动两个 HTTP 服务（daemon 随主进程退出）
    threads = [
        threading.Thread(
            target=run_http_layer,
            args=(args.http_port,),
            name="http-layer",
            daemon=True,
        ),
        threading.Thread(
            target=run_heartbeat,
            args=(args.heartbeat_port,),
            name="heartbeat",
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()

    logger.info("HTTP 层已启动: http://0.0.0.0:%d", args.http_port)
    logger.info("心跳接收已启动: http://0.0.0.0:%d", args.heartbeat_port)
    logger.info("AKO_hub 就绪。按 Ctrl+C 停止。")

    try:
        stop_event = threading.Event()
        while not stop_event.is_set():
            stop_event.wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("AKO_hub 已停止")


if __name__ == "__main__":
    main()