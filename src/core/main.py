"""
main.py — AKO_hub 总线调度 Agent 入口。

支持子命令：
  dispatch AGENT_ID       向指定 Agent 派发任务
  health-check            健康检查（巡检全部 Agent）

支持选项：
  --config CONFIG         指定配置文件路径
  --log-level LEVEL       日志级别
  --sync-registry         从注册中心同步 Agent 路由表
  --status                显示路由表状态
  --route INTENT          按意图路由到目标 Agent
  --route-to AGENT        直连指定 Agent

文档编号: AGE-TECH-AKO-HUB-020
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config_loader import load_config, HubConfig
from src.core.registry_client import RegistryClient
from src.core.routing_table import RoutingTable
from src.core.router import MessageRouter


# ── dispatch 辅助 ────────────────────────────────────────────────

def _load_table_and_router(config: HubConfig):
    """加载路由表并构建路由器。"""
    table = RoutingTable(config.routing_table_path)
    table.load()
    router = MessageRouter(config, table)
    return table, router


def setup_logging(level: str = "INFO", log_path: str = "logs/hub.log") -> None:
    """配置日志：同时输出到控制台和文件。"""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(PROJECT_ROOT / log_path), encoding="utf-8"),
        ],
    )


def cmd_sync_registry(config: HubConfig, logger: logging.Logger) -> None:
    """
    --sync-registry: 从注册中心拉取 Agent 信息，写入路由表。
    """
    logger.info("=" * 60)
    logger.info("开始同步注册表...")
    logger.info(f"注册中心: {config.registry_endpoint}")
    logger.info(f"注册中心 ID: {config.registry_agent_id}")

    # 1. 连接注册中心
    client = RegistryClient(config)
    agents = client.fetch_agents()

    if not agents:
        logger.error("注册中心返回空数据，跳过写入")
        return

    # 2. 写入路由表
    table = RoutingTable(config.routing_table_path)
    table.load()
    count = table.sync_from_agents(agents)
    table.save()

    # 3. 输出摘要
    logger.info(f"同步完成: {count} 个 Agent 已写入 {config.routing_table_path}")
    logger.info("Agent 列表:")
    for agent_id, info in sorted(agents.items()):
        status = info.get("status", "unknown")
        desc = info.get("description", "")[:40]
        logger.info(f"  [{status:>10}] {agent_id:<30} {desc}")


def cmd_status(config: HubConfig, logger: logging.Logger) -> None:
    """
    --status: 显示路由表当前状态。
    """
    table = RoutingTable(config.routing_table_path)
    table.load()

    router = MessageRouter(config, table)
    stats = router.get_stats()

    logger.info("=" * 60)
    logger.info("路由表状态:")
    logger.info(f"  策略:     {stats['strategy']}")
    logger.info(f"  总 Agent: {stats['total_agents']}")
    logger.info(f"  在线:     {stats['online_agents']}")
    logger.info(f"  最后同步: {stats['last_sync'] or '从未同步'}")

    if table.agent_count > 0:
        logger.info("")
        logger.info("Agent 列表:")
        for agent_id in sorted(table.list_agent_ids()):
            info = table.get_agent(agent_id)
            if info:
                status = info.get("status", "unknown")
                load = info.get("load", 0)
                priority = info.get("priority", "-")
                logger.info(f"  {agent_id:<30} status={status:<12} load={load} priority={priority}")


def cmd_route(config: HubConfig, logger: logging.Logger, intent: str = "", target: str = "") -> None:
    """
    --route / --route-to: 路由到目标 Agent。
    """
    table, router = _load_table_and_router(config)

    if table.agent_count == 0:
        logger.error("路由表为空，请先执行 --sync-registry")
        return

    if target:
        agent = router.route(target_agent=target)
    else:
        agent = router.route(intent=intent)

    if agent:
        logger.info(f"路由结果: {agent['agent_id']}")
        logger.info(f"  入口: {agent.get('entry_module', 'N/A')}")
        logger.info(f"  描述: {agent.get('description', 'N/A')}")
    else:
        logger.warning("未找到匹配的 Agent")


def cmd_dispatch(config: HubConfig, logger: logging.Logger, agent_id: str, test: bool = False) -> None:
    """
    dispatch: 向指定 Agent 派发任务。

    Args:
        agent_id: 目标 Agent ID
        test: 是否测试模式（仅验证连通性，不实际执行）
    """
    table, router = _load_table_and_router(config)

    if table.agent_count == 0:
        logger.error("路由表为空，请先执行 --sync-registry")
        return

    agent = table.get_agent(agent_id)
    if not agent:
        logger.error(f"Agent 不存在: {agent_id}")
        logger.info(f"可用 Agent: {', '.join(sorted(table.list_agent_ids())[:10])}...")
        return

    logger.info(f"{'[TEST] ' if test else ''}派发任务 → {agent_id}")
    logger.info(f"  入口模块: {agent.get('entry_module', 'N/A')}")
    logger.info(f"  入口函数: {agent.get('entry_function', 'run')}")
    logger.info(f"  调用模式: {agent.get('invoke_mode', 'importlib')}")
    logger.info(f"  描述: {agent.get('description', 'N/A')}")

    if test:
        # 测试模式：验证入口模块是否可导入
        entry_module = agent.get('entry_module', '')
        try:
            mod = __import__(entry_module.replace('/', '.').replace('.py', ''), fromlist=['run'])
            has_run = hasattr(mod, agent.get('entry_function', 'run'))
            logger.info(f"  [OK] 模块导入成功: {entry_module}")
            logger.info(f"  [OK] 入口函数 {'存在' if has_run else '不存在'}")
        except ImportError as e:
            logger.warning(f"  [WARN] 模块导入失败: {e}（Agent 项目可能不在本机）")

        logger.info(f"  [TEST] dispatch 测试完成: {agent_id}")
    else:
        # 正式模式：构建 payload 并通过子进程/importlib 调用
        import importlib
        entry_module = agent.get('entry_module', '')
        entry_function = agent.get('entry_function', 'run')
        invoke_mode = agent.get('invoke_mode', 'importlib')

        payload = {
            "intent": f"dispatch to {agent_id}",
            "agent_id": agent_id,
            "inputs": {},
        }

        if invoke_mode == "importlib":
            try:
                mod = importlib.import_module(entry_module)
                fn = getattr(mod, entry_function, None)
                if fn:
                    result = fn(**payload.get("inputs", {}))
                    logger.info(f"  执行结果: {json.dumps(result, ensure_ascii=False)[:200]}")
                else:
                    logger.error(f"  入口函数不存在: {entry_function}")
            except Exception as e:
                logger.error(f"  执行失败: {e}")
        else:
            logger.info(f"  subprocess 模式: 需通过 {entry_module} 执行")


def cmd_health_check(config: HubConfig, logger: logging.Logger) -> None:
    """
    health-check: 巡检全部 Agent 健康状态。

    通过 registry_client 重新拉取注册表，对比路由表，
    检查各 Agent 是否可达。
    """
    logger.info("=" * 60)
    logger.info("开始健康检查...")
    logger.info(f"注册中心: {config.registry_endpoint}")

    table, router = _load_table_and_router(config)

    if table.agent_count == 0:
        logger.error("路由表为空，请先执行 --sync-registry")
        return

    # 重新拉取注册表对比
    client = RegistryClient(config)
    remote_agents = client.fetch_agents()

    total = table.agent_count
    online = 0
    offline = 0
    missing = 0

    logger.info(f"路由表 Agent: {total} 个")
    logger.info(f"注册中心 Agent: {len(remote_agents)} 个")
    logger.info("")

    for agent_id in sorted(table.list_agent_ids()):
        info = table.get_agent(agent_id)
        if not info:
            continue

        in_remote = agent_id in remote_agents
        status = info.get("status", "unknown")
        heartbeat = info.get("last_heartbeat")

        if in_remote and status != "deprecated":
            online += 1
            mark = "OK"
        elif status == "deprecated":
            offline += 1
            mark = "DEPRECATED"
        else:
            missing += 1
            mark = "MISSING"

        hb_str = heartbeat or "无心跳"
        logger.info(f"  [{mark:>10}] {agent_id:<30} status={status:<12} {hb_str}")

    logger.info("")
    logger.info("健康检查完成:")
    logger.info(f"  总 Agent: {total}")
    logger.info(f"  在线: {online}")
    logger.info(f"  离线: {offline}")
    logger.info(f"  缺失: {missing}")


def main():
    parser = argparse.ArgumentParser(
        description="AKO Hub - Agent 总调度中枢",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/core/main.py --sync-registry
  python src/core/main.py --status
  python src/core/main.py dispatch AKO_quote_agent --test
  python src/core/main.py health-check
  python src/core/main.py --route "结构设计"
  python src/core/main.py --route-to AKO_chat
        """,
    )

    parser.add_argument(
        "--config",
        default="config/AKO_hub_config.yaml",
        help="配置文件路径 (default: config/AKO_hub_config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (default: INFO)",
    )

    # 子命令
    subparsers = parser.add_subparsers(dest="command")

    # dispatch 子命令
    dispatch_parser = subparsers.add_parser("dispatch", help="向指定 Agent 派发任务")
    dispatch_parser.add_argument("agent_id", help="目标 Agent ID")
    dispatch_parser.add_argument("--test", action="store_true", help="测试模式（仅验证连通性）")

    # health-check 子命令
    subparsers.add_parser("health-check", help="健康检查（巡检全部 Agent）")

    # 兼容旧 --flag 风格
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sync-registry", action="store_true", help="从注册中心同步 Agent 信息到路由表")
    group.add_argument("--status", action="store_true", help="显示路由表当前状态")
    group.add_argument("--route", type=str, metavar="INTENT", help="按意图路由到目标 Agent")
    group.add_argument("--route-to", type=str, metavar="AGENT_ID", help="直连指定 Agent")

    args = parser.parse_args()

    # 初始化日志
    setup_logging(args.log_level)
    logger = logging.getLogger("AKO_hub")

    logger.info("AKO Hub starting...")

    # 加载配置
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"配置加载失败: {e}")
        sys.exit(1)

    logger.info(f"Config: {args.config}")
    logger.info(f"Agent: {config.agent_id} ({config.agent_name})")
    logger.info(f"Strategy: {config.routing_strategy}")
    logger.info(f"Log level: {args.log_level}")

    # 分发命令：优先子命令，再 --flag
    if args.command == "dispatch":
        cmd_dispatch(config, logger, agent_id=args.agent_id, test=args.test)
    elif args.command == "health-check":
        cmd_health_check(config, logger)
    elif args.sync_registry:
        cmd_sync_registry(config, logger)
    elif args.status:
        cmd_status(config, logger)
    elif args.route:
        cmd_route(config, logger, intent=args.route)
    elif args.route_to:
        cmd_route(config, logger, target=args.route_to)
    else:
        logger.info("Hub core initialized. Use --help for commands.")
        logger.info("Routing table empty, waiting for registry sync.")


if __name__ == "__main__":
    main()
