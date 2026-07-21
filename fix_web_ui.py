"""
AKO Hub Web UI 快速修复脚本
自动检测和修复常见的启动问题
"""

import sys
import subprocess
from pathlib import Path

print("=" * 60)
print("AKO Hub Web UI 快速修复工具")
print("=" * 60)
print()

def run_command(cmd, description):
    """运行命令并显示结果"""
    print(f"[执行] {description}...")
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True,
            encoding='utf-8'
        )
        if result.returncode == 0:
            print(f"[✓] 成功")
            return True
        else:
            print(f"[✗] 失败")
            if result.stderr:
                print(f"    错误: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"[✗] 异常: {e}")
        return False

# 1. 检查 Python
print("[1/6] 检查 Python 环境...")
result = subprocess.run(["python", "--version"], capture_output=True, text=True)
if result.returncode == 0:
    print(f"[✓] Python 版本: {result.stdout.strip()}")
else:
    print("[✗] 未检测到 Python")
    print("    请先安装 Python 3.8+: https://www.python.org/downloads/")
    input("\n按回车键退出...")
    sys.exit(1)
print()

# 2. 升级 pip
print("[2/6] 升级 pip...")
run_command("python -m pip install --upgrade pip", "升级 pip")
print()

# 3. 安装/更新所有依赖
print("[3/6] 安装/更新项目依赖...")
requirements_file = Path("requirements.txt")
if requirements_file.exists():
    run_command("pip install -r requirements.txt --upgrade", "安装依赖包")
else:
    print("[!] 未找到 requirements.txt，使用默认依赖...")
    run_command("pip install gradio>=4.0.0 pyyaml>=6.0 langgraph>=0.0.40 chromadb>=0.4.22", "安装默认依赖")
print()

# 4. 检查配置文件
print("[4/6] 检查配置文件...")
config_file = Path("config/hub.yaml")
if not config_file.exists():
    print("[!] 配置文件不存在，正在初始化...")
    init_script = Path("scripts/init_hub.py")
    if init_script.exists():
        run_command("python scripts/init_hub.py", "运行初始化脚本")
    else:
        print("[✗] 未找到初始化脚本 scripts/init_hub.py")
else:
    print("[✓] 配置文件已存在")
print()

# 5. 检查数据库文件
print("[5/6] 检查数据库文件...")
db_files = list(Path(".").glob("*.db"))
if db_files:
    print(f"[✓] 找到 {len(db_files)} 个数据库文件")
    for db in db_files:
        print(f"    - {db.name}")
else:
    print("[!] 未找到数据库文件")
    print("    如果这是首次运行，请运行: python scripts/init_hub.py")
print()

# 6. 检查端口
print("[6/6] 检查端口 7860...")
try:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 7860))
    if result == 0:
        print("[⚠] 端口 7860 已被占用")
        print("    建议:")
        print("    1. 关闭已运行的 Web UI")
        print("    2. 或修改 web_ui.py 中的 server_port 参数")
    else:
        print("[✓] 端口 7860 可用")
    sock.close()
except Exception as e:
    print(f"[?] 无法检查端口: {e}")
print()

# 总结
print("=" * 60)
print("修复完成！")
print("=" * 60)
print()
print("现在可以尝试启动 Web UI:")
print()
print("  方式 1 (推荐): start_web_ui.bat")
print("  方式 2:        python web_ui.py")
print("  方式 3:        .\\start_web_ui.ps1 (PowerShell)")
print()
print("访问地址: http://127.0.0.1:7860")
print()
print("如仍有问题，请查看: WEB_UI_TROUBLESHOOTING.md")
print()

choice = input("是否现在启动 Web UI？(Y/N): ")
if choice.upper() == 'Y':
    print("\n正在启动 Web UI...")
    print("=" * 60)
    try:
        import web_ui
        app = web_ui.create_interface()
        app.launch(
            server_name="127.0.0.1",
            server_port=7860,
            share=False,
            show_error=True,
        )
    except KeyboardInterrupt:
        print("\n\nWeb UI 已停止")
    except Exception as e:
        print(f"\n[错误] 启动失败: {e}")
        print("\n请查看完整错误信息，或参考 WEB_UI_TROUBLESHOOTING.md")
else:
    print("\n好的，您可以稍后手动启动。")
