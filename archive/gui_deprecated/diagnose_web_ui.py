"""
AKO Hub Web UI 诊断脚本
用于排查 Web UI 无法启动的问题
"""

import sys
import os
from pathlib import Path

print("=" * 60)
print("AKO Hub Web UI 诊断工具")
print("=" * 60)
print()

# 1. 检查 Python 版本
print("[1/6] 检查 Python 版本...")
print(f"  Python 版本: {sys.version}")
print(f"  Python 路径: {sys.executable}")
print()

# 2. 检查 gradio 安装
print("[2/6] 检查 gradio 依赖...")
try:
    import gradio
    print(f"  ✓ gradio 已安装 (版本: {gradio.__version__})")
    
    # 检查版本兼容性
    version_parts = gradio.__version__.split('.')
    major_version = int(version_parts[0])
    minor_version = int(version_parts[1]) if len(version_parts) > 1 else 0
    
    if major_version < 4 or (major_version == 4 and minor_version < 0):
        print(f"  ⚠ 警告：Gradio 版本 {gradio.__version__} 可能过旧")
        print(f"  建议升级到 4.0.0 或更高版本以获得最佳体验")
        print(f"  运行: pip install gradio>=4.0.0 --upgrade")
except ImportError as e:
    print(f"  ✗ gradio 未安装或导入失败: {e}")
    print("  解决方案: pip install gradio>=4.0.0")
    sys.exit(1)
print()

# 3. 检查配置文件
print("[3/6] 检查配置文件...")
config_path = Path("config/hub.yaml")
if config_path.exists():
    print(f"  ✓ 配置文件存在: {config_path.resolve()}")
else:
    print(f"  ✗ 配置文件不存在: {config_path.resolve()}")
    print("  解决方案: 运行 python scripts/init_hub.py")
print()

# 4. 检查 hub_api 导入
print("[4/6] 检查 hub_api 模块...")
try:
    from hub_api import submit_task, sync_check, hub_status, list_files
    print("  ✓ hub_api 模块导入成功")
except Exception as e:
    print(f"  ✗ hub_api 导入失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# 5. 检查 web_ui 模块
print("[5/6] 检查 web_ui 模块...")
try:
    from web_ui import create_interface
    print("  ✓ web_ui 模块导入成功")
except Exception as e:
    print(f"  ✗ web_ui 导入失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# 6. 检查端口占用
print("[6/6] 检查端口 7860...")
try:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 7860))
    if result == 0:
        print("  ⚠ 端口 7860 已被占用")
        print("  解决方案: ")
        print("    - 关闭占用端口的程序")
        print("    - 或修改 web_ui.py 中的 server_port 参数")
    else:
        print("  ✓ 端口 7860 可用")
    sock.close()
except Exception as e:
    print(f"  ? 无法检查端口: {e}")
print()

# 总结
print("=" * 60)
print("诊断完成！")
print("=" * 60)
print()
print("如果所有检查都通过，请尝试:")
print("  python web_ui.py")
print()
print("如遇问题，请将上述输出信息提供给技术支持。")
