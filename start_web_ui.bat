@echo off
chcp 65001 >nul
REM AKO Hub Web UI 快速启动脚本（增强版）
REM 自动处理依赖安装和错误诊断

echo ========================================
echo   AKO Hub Web UI 启动脚本
echo ========================================
echo.

REM 检查 Python 是否安装
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo.
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [✓] Python 环境检测通过
python --version
echo.

REM 检查并安装依赖
echo [1/4] 检查依赖包...
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [!] streamlit 未安装，正在安装...
    echo.
    pip install streamlit>=1.28.0
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败！
        echo.
        echo 请尝试以下解决方案：
        echo 1. 检查网络连接
        echo 2. 以管理员身份运行此脚本
        echo 3. 手动运行: pip install streamlit>=1.28.0
        echo.
        pause
        exit /b 1
    )
    echo [✓] 依赖安装成功
) else (
    echo [✓] streamlit 已安装
    python -c "import streamlit; print('    版本:', streamlit.__version__)"
)

echo.
echo [2/4] 检查其他依赖...
python -c "import yaml" >nul 2>&1
if errorlevel 1 (
    echo [!] pyyaml 未安装，正在安装...
    pip install pyyaml>=6.0
)

python -c "import langgraph" >nul 2>&1
if errorlevel 1 (
    echo [!] langgraph 未安装，正在安装...
    pip install langgraph>=0.0.40
)

python -c "import chromadb" >nul 2>&1
if errorlevel 1 (
    echo [!] chromadb 未安装，正在安装...
    pip install chromadb>=0.4.22
)
echo [✓] 所有依赖检查完成

echo.
echo [3/4] 检查配置文件...
if not exist "config\hub.yaml" (
    echo [警告] 未找到 config\hub.yaml
    echo.
    echo 如未初始化，请先运行:
    echo   python scripts\init_hub.py
    echo.
    choice /C YN /M "是否继续启动"
    if errorlevel 2 exit /b 1
) else (
    echo [✓] 配置文件存在
)

echo.
echo [4/4] 检查端口占用...
netstat -ano | findstr :7860 | findstr LISTENING >nul
if not errorlevel 1 (
    echo [警告] 端口 7860 已被占用！
    echo.
    echo 可能的原因：
    echo   1. Web UI 已经在运行
    echo   2. 其他程序占用了该端口
    echo.
    echo 解决方案：
    echo   - 关闭已运行的 Web UI（按 Ctrl+C）
    echo   - 或编辑 web_ui.py，修改 server_port 为其他值（如 7861）
    echo.
    choice /C YN /M "是否继续尝试启动"
    if errorlevel 2 exit /b 1
) else (
    echo [✓] 端口 7860 可用
)

echo.
echo ========================================
echo 启动 Web UI...
echo ========================================
echo.
echo 🌐 浏览器访问地址: http://127.0.0.1:7860
echo.
echo 💡 提示:
echo    - 按 Ctrl+C 可停止服务
echo    - 如遇问题请查看下方错误信息
echo    - 详细故障排查请参考: WEB_UI_TROUBLESHOOTING.md
echo.
echo ========================================
echo.

REM 先运行诊断脚本
echo [诊断] 运行系统检查...
python diagnose_web_ui.py
echo.

REM 启动 Web UI 并捕获错误
streamlit run streamlit_app.py --server.port 7860 --server.address 127.0.0.1

if errorlevel 1 (
    echo.
    echo ========================================
    echo [错误] Web UI 启动失败！
    echo ========================================
    echo.
    echo 常见原因及解决方案：
    echo.
    echo 1. 端口被占用
    echo    解决: 编辑 web_ui.py，修改 server_port 为其他值
    echo.
    echo 2. 配置文件错误
    echo    解决: 检查 config\hub.yaml 格式是否正确
    echo.
    echo 3. 数据库文件损坏
    echo    解决: 重新运行 python scripts\init_hub.py
    echo.
    echo 4. 依赖版本冲突
    echo    解决: 运行 pip install -r requirements.txt --upgrade
    echo.
    echo 5. 权限问题
    echo    解决: 右键点击此脚本，选择"以管理员身份运行"
    echo.
    echo 详细排查指南: WEB_UI_TROUBLESHOOTING.md
    echo.
    pause
)
