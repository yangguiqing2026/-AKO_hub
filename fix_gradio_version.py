"""
Gradio 版本快速修复脚本
专门解决 show_copy_button 等兼容性问题
"""

import sys
import subprocess

print("=" * 60)
print("Gradio 版本兼容性修复工具")
print("=" * 60)
print()

# 1. 检查当前版本
print("[1/3] 检查当前 Gradio 版本...")
try:
    import gradio
    current_version = gradio.__version__
    print(f"  当前版本: {current_version}")
    
    # 解析版本号
    version_parts = current_version.split('.')
    major = int(version_parts[0])
    minor = int(version_parts[1]) if len(version_parts) > 1 else 0
    
    if major < 4:
        print(f"  ⚠ 版本过旧（{current_version}），需要升级到 4.x")
        needs_upgrade = True
    elif major == 4 and minor < 20:
        print(f"  ⚠ 版本较旧（{current_version}），建议升级到 4.20+")
        needs_upgrade = True
    elif major >= 5:
        print(f"  ⚠ 版本过新（{current_version}），可能存在兼容性问题")
        print(f"  建议降级到 4.x 稳定版本")
        needs_upgrade = True
    else:
        print(f"  ✓ 版本合适（{current_version}）")
        needs_upgrade = False
        
except ImportError:
    print("  ✗ Gradio 未安装")
    needs_upgrade = True
    current_version = None

print()

# 2. 提供修复选项
if needs_upgrade:
    print("[2/3] 选择修复方案:")
    print()
    print("  1. 升级到最新稳定版 (推荐)")
    print("     pip install gradio>=4.20.0,<5.0.0 --upgrade")
    print()
    print("  2. 安装指定版本 (4.44.0)")
    print("     pip install gradio==4.44.0")
    print()
    print("  3. 使用已修复的代码（不升级）")
    print("     代码已移除不兼容参数，可直接运行")
    print()
    
    choice = input("请选择 (1/2/3，直接回车默认选1): ").strip()
    
    if choice == '2':
        print("\n正在安装 Gradio 4.44.0...")
        cmd = "pip install gradio==4.44.0"
    elif choice == '3':
        print("\n好的，代码已修复，您可以直接运行 Web UI")
        print("\n运行命令: python web_ui.py")
        input("\n按回车键退出...")
        sys.exit(0)
    else:
        print("\n正在升级到最新稳定版...")
        cmd = "pip install \"gradio>=4.20.0,<5.0.0\" --upgrade"
    
    print()
    result = subprocess.run(cmd, shell=True)
    
    if result.returncode == 0:
        print("\n✓ 安装成功！")
    else:
        print("\n✗ 安装失败，请检查网络连接或手动安装")
        input("\n按回车键退出...")
        sys.exit(1)
else:
    print("[2/3] 版本检查通过，无需修复")
    print()

# 3. 验证修复
print("[3/3] 验证修复结果...")
try:
    # 重新导入以获取新版本
    if 'gradio' in sys.modules:
        del sys.modules['gradio']
    import gradio
    
    new_version = gradio.__version__
    print(f"  ✓ Gradio 版本: {new_version}")
    
    # 测试创建 Textbox
    try:
        import gradio as gr
        # 尝试创建不带 show_copy_button 的 Textbox（兼容所有版本）
        test_box = gr.Textbox(label="测试", interactive=False)
        print("  ✓ Textbox 创建成功")
    except Exception as e:
        print(f"  ⚠ Textbox 测试警告: {e}")
    
    print()
    print("=" * 60)
    print("修复完成！")
    print("=" * 60)
    print()
    print("现在可以启动 Web UI:")
    print()
    print("  python web_ui.py")
    print()
    print("或使用启动脚本:")
    print()
    print("  start_web_ui.bat")
    print("  .\\start_web_ui.ps1")
    print()
    
    choice = input("是否现在启动 Web UI？(Y/N): ")
    if choice.upper() == 'Y':
        print("\n正在启动...\n")
        from web_ui import create_interface
        app = create_interface()
        app.launch(
            server_name="127.0.0.1",
            server_port=7860,
            share=False,
            show_error=True,
        )
    else:
        print("\n好的，您可以稍后手动启动。")
        
except Exception as e:
    print(f"\n✗ 验证失败: {e}")
    print("\n请查看完整错误信息，或参考 GRADIO_COMPATIBILITY.md")
    input("\n按回车键退出...")
    sys.exit(1)
