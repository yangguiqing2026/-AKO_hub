@echo off
chcp 65001 >nul
title AKO Hub - 一键启动
cd /d D:\AKO_Hub

echo ============================================================
echo   AKO Hub 一键启动
echo ============================================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确认已安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查 venv
if not exist "venv\Scripts\python.exe" (
    echo [警告] 未找到 Hub 虚拟环境，使用系统 Python
    set PYTHON=python
) else (
    echo [OK] 使用虚拟环境: venv
    set PYTHON=venv\Scripts\python.exe
)

:: 检查 Ollama
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if errorlevel 1 (
    echo [提示] 正在启动 Ollama...
    start "" /B ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
) else (
    echo [OK] Ollama 已在运行
)

:: 检查 .env
if not exist ".env" (
    echo [警告] 未找到 .env 文件，请从 .env.template 复制并填入 API Key
    echo         copy .env.template .env
)

echo.
echo ============================================================
echo   启动服务...
echo ============================================================
echo.

:: 启动后台服务
echo [1/3] 启动 AKO_knowledge API (端口 8000)...
start "AKO_knowledge" /MIN cmd /c "cd /d D:\AKO_knowledge && python knowledge_service.py"

echo [2/3] 启动 AKO_chat 服务 (端口 7861)...
start "AKO_chat" /MIN cmd /c "cd /d D:\AKO_chat && python chat_app.py"

echo [3/3] 启动 AKO Hub Web UI (端口 7860)...
echo.
echo   浏览器将自动打开 http://127.0.0.1:7860
echo   按 Ctrl+C 可停止 Hub UI
echo   关闭此窗口不会停止后台服务
echo ============================================================
echo.

:: 等待 2 秒后打开浏览器
timeout /t 2 /nobreak >nul
start http://127.0.0.1:7860

:: 启动 Hub Web UI（前台阻塞）
%PYTHON% web_ui.py

:: 清理
echo.
echo Hub Web UI 已停止。
pause
