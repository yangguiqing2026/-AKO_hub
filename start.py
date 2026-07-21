#!/usr/bin/env python3
"""
AKO Hub 快速启动脚本
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

def show_help():
    """显示帮助信息"""
    print("""
AKO Hub - 统一调度平台
=====================

可用命令:
  init          - 初始化 AKO Hub (首次使用)
  status        - 查看系统状态
  run           - 运行任务 (需要参数)
  sync          - 执行同步校验
  list-files    - 列出文件
  help          - 显示此帮助信息

示例:
  python start.py init
  python start.py status
  python start.py run --intent "结构计算"
  python start.py sync --project taoli
  python start.py list-files --project taoli
    """)

def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1]
    
    if command == "help":
        show_help()
    elif command == "init":
        # 运行初始化脚本
        from scripts.init_hub import main as init_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # 移除 'init' 参数
        init_main()
    elif command == "status":
        # 运行状态查询
        from master.runner import cmd_status
        import argparse
        args = argparse.Namespace()
        cmd_status(args)
    elif command == "run":
        # 运行任务
        from master.runner import main as runner_main
        sys.argv = [sys.argv[0], "run"] + sys.argv[2:]  # 替换 'run' 为子命令
        runner_main()
    elif command == "sync":
        # 执行同步校验
        from master.runner import main as runner_main
        sys.argv = [sys.argv[0], "sync"] + sys.argv[2:]
        runner_main()
    elif command == "list-files":
        # 列出文件
        from master.runner import main as runner_main
        sys.argv = [sys.argv[0], "list-files"] + sys.argv[2:]
        runner_main()
    else:
        print(f"未知命令: {command}")
        show_help()

if __name__ == "__main__":
    main()