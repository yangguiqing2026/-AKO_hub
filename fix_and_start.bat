@echo off
chcp 65001 >nul
REM AKO Hub Web UI 一键修复脚本
REM 自动安装依赖并启动

echo ========================================
echo   AKO Hub Web UI 一键修复
echo ========================================
echo.

echo [步骤 1] 安装/更新 gradio...
pip install gradio>=4.0.0 pyyaml langgraph chromadb
if errorlevel 1 (
    echo.
    echo [错误] 安装失败，尝试使用国内镜像源...
    pip install gradio>=4.0.0 pyyaml langgraph chromadb -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo [步骤 2] 验证安装...
python -c "import gradio; print('Gradio 版本:', gradio.__version__)"
if errorlevel 1 (
    echo.
    echo [错误] gradio 仍未安装成功
    echo.
    echo 请尝试以下方法：
    echo 1. 以管理员身份运行此脚本
    echo 2. 检查网络连接
    echo 3. 手动运行: pip install gradio
    pause
    exit /b 1
)

echo.
echo [步骤 3] 启动 Web UI...
echo ========================================
echo.
echo 正在启动，请稍候...
echo.

python web_ui.py

pause
