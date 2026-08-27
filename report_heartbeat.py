"""
report_heartbeat.py — Agent 心跳上报脚本（真实 Agent 集成用）。

让真实 Agent 定时向 Hub 上报心跳（含 CPU/内存/磁盘等系统资源），
Hub 看板据此在 90 秒内判定为「在线」并显示绿色心跳脉冲。

用法:
    # 单个 Agent 上报
    python report_heartbeat.py --agent-id AKO_law_agent

    # 全部已注册 Agent 上报（读取 config/agent_names.yaml）
    python report_heartbeat.py --all

    # 自定义间隔与 Hub 地址
    python report_heartbeat.py --all --interval 30 --hub http://127.0.0.1:5000/heartbeat

说明:
    生产环境下，各 Agent 应在自己的进程内 import HeartbeatClient 并 start()；
    本脚本用于独立进程方式的上报，或作为各 Agent 尚未嵌入客户端时的过渡方案。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from heartbeat.AKO_heartbeat_client import HeartbeatClient  # noqa: E402


def load_agent_ids() -> list[str]:
    """读取 config/agent_names.yaml 中的全部 agent_id。"""
    try:
        import yaml
        cfg_path = PROJECT_ROOT / "config" / "agent_names.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return list((cfg.get("agents", {}) or {}).keys())
    except Exception:
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AKO Agent 心跳上报")
    parser.add_argument("--agent-id", help="单个 Agent ID")
    parser.add_argument("--all", action="store_true", help="上报全部已注册 Agent")
    parser.add_argument("--interval", type=int, default=30, help="心跳间隔秒数（默认 30，最小 5）")
    parser.add_argument("--hub", default="http://127.0.0.1:5000/heartbeat", help="Hub 心跳端点")
    args = parser.parse_args(argv)

    if args.all:
        agent_ids = load_agent_ids()
    elif args.agent_id:
        agent_ids = [args.agent_id]
    else:
        parser.error("请指定 --agent-id 或 --all")

    if not agent_ids:
        print("未找到 Agent，请确认 config/agent_names.yaml")
        return 1

    clients = []
    for aid in agent_ids:
        c = HeartbeatClient(agent_id=aid, hub_url=args.hub, heartbeat_interval=args.interval)
        c.start()
        clients.append(c)
        print(f"  心跳线程已启动: {aid}  (interval={args.interval}s)")

    print(f"\n共 {len(clients)} 个 Agent 心跳上报中，按 Ctrl+C 停止。\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止心跳上报...")
        for c in clients:
            c.stop()
        print("已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
