# -*- coding: utf-8 -*-
"""守护清单守卫（2026-09-16）。

现场：集群巡检（AKO_cluster_guardian_agent）不在 supervisor 清单、也没有计划任务，
日志自 2026-08-25 起为空、心跳表 0 行 —— 长期无人拉起（其 daemon 模式本身是好的）。
这类"漏配一个名字"的缺口没有运行时症状，故在此看守。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = (PROJECT_ROOT / "scripts" / "agent_supervisor.py").read_text(encoding="utf-8")


def test_cluster_guardian_is_supervised() -> None:
    assert '"AKO_cluster_guardian_agent"' in SRC
    assert "CLUSTER_GUARDIAN_DIR" in SRC
    assert "probe_cluster_guardian" in SRC


def test_cluster_guardian_runs_in_daemon_mode() -> None:
    """守护入口必须是 --mode daemon（once 是一次性巡检，交给别处调度）。"""
    assert '"--mode", "daemon"' in SRC
