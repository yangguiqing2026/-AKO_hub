#!/usr/bin/env python3
"""
AKO Hub — 统一 CLI 入口
cli.py: 将所有 Spoke 项目的命令行接口统一到一个入口。

用法:
    python cli.py                     # 显示帮助
    python cli.py hub status          # Hub 状态
    python cli.py hub run --intent "..." --project taoli
    python cli.py hub sync
    python cli.py architect "设计需求"   # 转发到 architect_agent
    python cli.py architect --ask "问题"
    python cli.py inspector inspect file.dwg --project taoli
    python cli.py image analyze photo.jpg
    python cli.py chat                # 启动 AKO_chat 服务
    python cli.py workflow --file input.docx
    python cli.py knowledge           # 启动 AKO_knowledge API
    python cli.py ui                  # 启动 Gradio Web UI
    python cli.py launch              # 一键启动全部服务

文档编号: AGE-TECH-AKO-HUB-001 §CLI
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

# ── 路径常量 ───────────────────────────────────────────────────────
HUB_ROOT = Path(__file__).resolve().parent
SPOKE_DIRS = {
    "architect":  "D:/AKO_architect_agent",
    "inspector":  "D:/AKO_drawing_inspector",
    "image":      "D:/AKO_image_analyzer",
    "chat":       "D:/AKO_chat",
    "workflow":   "D:/AKO工作流",
    "knowledge":  "D:/AKO_knowledge",
    "geo":        str(HUB_ROOT / "ako_geo"),
}

# ── 辅助函数 ───────────────────────────────────────────────────────

def _run_in_dir(cwd: str, cmd: list, python_args: list = None):
    """在指定目录下执行 Python 脚本。"""
    if not Path(cwd).exists():
        print(f"  目录不存在: {cwd}")
        return 1

    # 构建完整命令
    py = sys.executable
    full_cmd = [py] + cmd

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        # 非阻塞启动：子进程继承 stdin/stdout/stderr，实现实时输出
        proc = subprocess.Popen(
            full_cmd,
            cwd=cwd,
            env=env,
        )
        return proc.wait()
    except KeyboardInterrupt:
        print("\n  已中断")
        return 130
    except Exception as e:
        print(f"  执行失败: {e}")
        return 1


def _spoke_python(spoke_dir: str) -> str:
    """检测 Spoke 是否有独立 venv，有则用 venv 的 python。"""
    venv_py = Path(spoke_dir) / "venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _run_spoke(spoke_key: str, script: str, args: list):
    """在 Spoke 目录下运行指定脚本。"""
    spoke_dir = SPOKE_DIRS.get(spoke_key)
    if not spoke_dir:
        print(f"  未知的 Spoke: {spoke_key}")
        return 1

    spoke_dir = str(Path(spoke_dir))
    if not Path(spoke_dir).exists():
        print(f"  Spoke 目录不存在: {spoke_dir}")
        return 1

    py = _spoke_python(spoke_dir)
    cmd = [py, script] + args

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        # 非阻塞启动：子进程继承 stdin/stdout/stderr，实现实时输出
        proc = subprocess.Popen(cmd, cwd=spoke_dir, env=env)
        return proc.wait()
    except KeyboardInterrupt:
        print("\n  已中断")
        return 130
    except Exception as e:
        print(f"  执行失败: {e}")
        return 1


# ── Hub 子命令 ─────────────────────────────────────────────────────

def cmd_hub(args):
    """代理到 Hub 的 start.py。"""
    hub_args = [str(HUB_ROOT / "start.py")] + args.hub_args
    return _run_in_dir(str(HUB_ROOT), hub_args)


# ── Architect Agent ────────────────────────────────────────────────

def cmd_architect(args):
    """代理到 AKO_architect_agent/main.py。"""
    return _run_spoke("architect", "main.py", args.arch_args)


# ── Drawing Inspector ──────────────────────────────────────────────

def cmd_inspector(args):
    """代理到 AKO_drawing_inspector/cli/cli.py。"""
    return _run_spoke("inspector", "cli/cli.py", args.insp_args)


# ── Image Analyzer ─────────────────────────────────────────────────

def cmd_image(args):
    """代理到 AKO_image_analyzer/cli/cli.py。"""
    return _run_spoke("image", "cli/cli.py", args.img_args)


# ── AKO Chat ──────────────────────────────────────────────────────

def cmd_chat(args):
    """启动 AKO_chat Web 服务。"""
    spoke_dir = SPOKE_DIRS["chat"]
    if not Path(spoke_dir).exists():
        print(f"  AKO_chat 目录不存在: {spoke_dir}")
        return 1

    py = _spoke_python(spoke_dir)
    print("  启动 AKO_chat 服务 (端口 7861)...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen([py, "chat_app.py"], cwd=spoke_dir, env=env)
        return proc.wait()
    except KeyboardInterrupt:
        print("\n  已中断")
        return 130
    except Exception as e:
        print(f"  执行失败: {e}")
        return 1


# ── AKO 工作流 ─────────────────────────────────────────────────────

def cmd_workflow(args):
    """代理到 AKO工作流/main.py。"""
    return _run_spoke("workflow", "main.py", args.wf_args)


# ── AKO Knowledge ─────────────────────────────────────────────────

def cmd_knowledge(args):
    """启动 AKO_knowledge API 服务。"""
    spoke_dir = SPOKE_DIRS["knowledge"]
    if not Path(spoke_dir).exists():
        print(f"  AKO_knowledge 目录不存在: {spoke_dir}")
        return 1

    py = _spoke_python(spoke_dir)
    print("  启动 AKO_knowledge API (端口 8000)...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen(
            [py, "-m", "uvicorn", "knowledge_service:app",
             "--host", "127.0.0.1", "--port", "8000"],
            cwd=spoke_dir,
            env=env,
        )
        return proc.wait()
    except KeyboardInterrupt:
        print("\n  已中断")
        return 130
    except Exception as e:
        print(f"  执行失败: {e}")
        return 1


# ── AKO GEO（内容营销×GEO×知识发酵）─────────────────────────────────

def cmd_geo(args):
    """启动 AKO_geo GEO 内容生成服务。"""
    print("  启动 AKO_geo GEO 内容生成...")
    return _run_in_dir(str(HUB_ROOT), ["-m", "ako_geo.spoke"] + args.geo_args)


# ── Web UI ─────────────────────────────────────────────────────────

def cmd_ui(args):
    """启动 Hub Dashboard（FastAPI，端口 80）。"""
    print("  启动 AKO Hub Web UI (端口 80，http://AKOagent)...")
    return _run_in_dir(str(HUB_ROOT), ["dashboard/app.py"])


# ── 一键启动 ───────────────────────────────────────────────────────

def cmd_launch(args):
    """依次启动所有后台服务，最后启动 Web UI。"""
    import time

    services = [
        ("knowledge", "AKO_knowledge API", "127.0.0.1:8000"),
        ("chat",      "AKO_chat 服务",       "127.0.0.1:7861"),
    ]

    procs = []
    for key, label, addr in services:
        spoke_dir = SPOKE_DIRS[key]
        if not Path(spoke_dir).exists():
            print(f"  跳过 {label}（目录不存在）")
            continue

        py = _spoke_python(spoke_dir)
        if key == "knowledge":
            cmd = [py, "-m", "uvicorn", "knowledge_service:app",
                   "--host", "127.0.0.1", "--port", "8000"]
        else:
            cmd = [py, "chat_app.py"]

        print(f"  启动 {label} ({addr})...")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(cmd, cwd=spoke_dir, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        procs.append((label, proc))
        time.sleep(1)

    # 最后启动 Web UI（前台，阻塞）
    print("  启动 AKO Hub Web UI (http://AKOagent)...")
    print("  所有服务已启动，按 Ctrl+C 停止\n")

    ui_proc = None
    try:
        ui_proc = subprocess.Popen(
            [sys.executable, "dashboard/app.py"],
            cwd=str(HUB_ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        ui_proc.wait()
    except KeyboardInterrupt:
        print("\n  正在停止所有服务...")
        if ui_proc is not None and ui_proc.poll() is None:
            ui_proc.terminate()

    # 清理后台进程
    for label, proc in procs:
        if proc.poll() is None:
            proc.terminate()
            print(f"  已停止 {label}")

    print("  所有服务已停止")
    return 0


# ── 状态总览 ───────────────────────────────────────────────────────

def cmd_status_all(args):
    """显示所有项目的状态。"""
    print("=" * 60)
    print("  AKO Hub 全局状态")
    print("=" * 60)

    # 1. 检查各 Spoke 目录
    print("\n  Spoke 目录状态:")
    for key, d in SPOKE_DIRS.items():
        exists = Path(d).exists()
        icon = "+" if exists else "-"
        print(f"    [{icon}] {key:12s} {d}")

    # 2. 检查 Hub 数据库
    db_path = HUB_ROOT / "hub_meta.db"
    print(f"\n  Hub 数据库: {'+' if db_path.exists() else '-'} {db_path}")

    # 3. 检查 ChromaDB
    chroma_path = HUB_ROOT / "chroma_db"
    print(f"  ChromaDB:    {'+' if chroma_path.exists() else '-'} {chroma_path}")

    # 4. 检查 .env
    env_path = HUB_ROOT / ".env"
    print(f"  .env 配置:   {'+' if env_path.exists() else '-'} {env_path}")

    # 5. 检查端口占用（简单检测）
    print("\n  端口状态:")
    import socket
    ports = {
        80: "Hub Dashboard Web UI",
        7861: "AKO_chat",
        8000: "AKO_knowledge API",
        8501: "image_analyzer Streamlit",
    }
    for port, label in ports.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        status = "运行中" if result == 0 else "未启动"
        icon = "+" if result == 0 else "-"
        print(f"    [{icon}] {port}: {label} ({status})")

    # 6. 注册表信息
    print("\n  已注册 Spoke:")
    try:
        sys.path.insert(0, str(HUB_ROOT))
        from registry.workflows import list_all_spokes
        spokes = list_all_spokes()
        for s in spokes:
            print(f"    [{s['status'][:4]}] {s['name']:30s} {s['spoke_type']:10s} {s['description'][:30]}")
    except Exception as e:
        print(f"    无法加载注册表: {e}")

    print()
    return 0


# ── 构建 argparse ─────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ako",
        description="AKO Hub 统一 CLI — 一个入口管理所有 Spoke",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli.py status                    # 全局状态
  python cli.py hub run --intent "..."    # Hub 任务
  python cli.py architect "结构设计"       # architect_agent
  python cli.py architect --ask "问题"     # 智能问答
  python cli.py inspector inspect x.dwg --project taoli
  python cli.py image analyze photo.jpg
  python cli.py workflow --file input.docx
  python cli.py chat                      # 启动 chat 服务
  python cli.py knowledge                 # 启动 knowledge API
  python cli.py ui                        # 启动 Web UI
  python cli.py launch                    # 一键启动全部
        """,
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # status
    p_status = sub.add_parser("status", help="全局状态总览")
    p_status.set_defaults(func=cmd_status_all)

    # hub
    p_hub = sub.add_parser("hub", help="Hub 命令（run/sync/init/status/list-files）")
    p_hub.add_argument("hub_args", nargs=argparse.REMAINDER, help="转发给 start.py 的参数")
    p_hub.set_defaults(func=cmd_hub)

    # architect
    p_arch = sub.add_parser("architect", help="AKO_architect_agent")
    p_arch.add_argument("arch_args", nargs=argparse.REMAINDER, help="转发给 main.py 的参数")
    p_arch.set_defaults(func=cmd_architect)

    # inspector
    p_insp = sub.add_parser("inspector", help="AKO_drawing_inspector")
    p_insp.add_argument("insp_args", nargs=argparse.REMAINDER, help="转发给 cli.py 的参数")
    p_insp.set_defaults(func=cmd_inspector)

    # image
    p_img = sub.add_parser("image", help="AKO_image_analyzer")
    p_img.add_argument("img_args", nargs=argparse.REMAINDER, help="转发给 cli.py 的参数")
    p_img.set_defaults(func=cmd_image)

    # chat
    p_chat = sub.add_parser("chat", help="启动 AKO_chat 服务")
    p_chat.set_defaults(func=cmd_chat)

    # workflow
    p_wf = sub.add_parser("workflow", help="AKO 工作流")
    p_wf.add_argument("wf_args", nargs=argparse.REMAINDER, help="转发给 main.py 的参数")
    p_wf.set_defaults(func=cmd_workflow)

    # geo
    p_geo = sub.add_parser("geo", help="AKO_geo 内容营销×GEO×知识发酵")
    p_geo.add_argument("geo_args", nargs=argparse.REMAINDER, help="转发给 ako_geo 的参数")
    p_geo.set_defaults(func=cmd_geo)

    # knowledge
    p_kb = sub.add_parser("knowledge", help="启动 AKO_knowledge API")
    p_kb.set_defaults(func=cmd_knowledge)

    # ui
    p_ui = sub.add_parser("ui", help="启动 Hub Dashboard Web UI（端口 80）")
    p_ui.set_defaults(func=cmd_ui)

    # launch
    p_launch = sub.add_parser("launch", help="一键启动所有服务")
    p_launch.set_defaults(func=cmd_launch)

    return parser


# ── 主入口 ─────────────────────────────────────────────────────────

def main():
    parser = build_parser()

    # 无参数时显示帮助
    if len(sys.argv) < 2:
        parser.print_help()
        return 0

    args = parser.parse_args()

    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
