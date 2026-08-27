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

logger = logging.getLogger(__name__)


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