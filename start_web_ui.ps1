# AKO Hub Web UI PowerShell 启动脚本
# 使用方法: .\start_web_ui.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AKO Hub Web UI 启动脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
Write-Host "[1/3] 检查 Python 环境..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[✓] Python 环境检测通过" -ForegroundColor Green
    Write-Host "    $pythonVersion" -ForegroundColor Gray
} catch {
    Write-Host "[错误] 未检测到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    Write-Host ""
    Write-Host "下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}

Write-Host ""
Write-Host "[2/3] 检查依赖包..." -ForegroundColor Cyan

# 检查 streamlit
try {
    python -c "import streamlit" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[✓] streamlit 已安装" -ForegroundColor Green
        $stVersion = python -c "import streamlit; print(streamlit.__version__)" 2>$null
        Write-Host "    版本: $stVersion" -ForegroundColor Gray
    } else {
        throw "Not installed"
    }
} catch {
    Write-Host "[!] streamlit 未安装，正在安装..." -ForegroundColor Yellow
    Write-Host ""
    
    pip install streamlit>=1.28.0
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[错误] 依赖安装失败！" -ForegroundColor Red
        Write-Host ""
        Write-Host "请尝试以下解决方案：" -ForegroundColor Yellow
        Write-Host "1. 以管理员身份运行 PowerShell" -ForegroundColor White
        Write-Host "2. 检查网络连接" -ForegroundColor White
        Write-Host "3. 手动运行: pip install streamlit>=1.28.0" -ForegroundColor White
        Write-Host ""
        Read-Host "按回车退出"
        exit 1
    }
    
    Write-Host "[✓] 依赖安装成功" -ForegroundColor Green
}

# 检查 yaml
try {
    python -c "import yaml" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[✓] pyyaml 已安装" -ForegroundColor Green
    } else {
        throw "Not installed"
    }
} catch {
    Write-Host "[!] pyyaml 未安装，正在安装..." -ForegroundColor Yellow
    pip install pyyaml>=6.0
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败！" -ForegroundColor Red
        exit 1
    }
    Write-Host "[✓] pyyaml 安装成功" -ForegroundColor Green
}

# 检查 langgraph
try {
    python -c "import langgraph" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[✓] langgraph 已安装" -ForegroundColor Green
    } else {
        throw "Not installed"
    }
} catch {
    Write-Host "[!] langgraph 未安装，正在安装..." -ForegroundColor Yellow
    pip install langgraph>=0.0.40
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败！" -ForegroundColor Red
        exit 1
    }
    Write-Host "[✓] langgraph 安装成功" -ForegroundColor Green
}

# 检查 chromadb
try {
    python -c "import chromadb" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[✓] chromadb 已安装" -ForegroundColor Green
    } else {
        throw "Not installed"
    }
} catch {
    Write-Host "[!] chromadb 未安装，正在安装..." -ForegroundColor Yellow
    pip install chromadb>=0.4.22
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败！" -ForegroundColor Red
        exit 1
    }
    Write-Host "[✓] chromadb 安装成功" -ForegroundColor Green
}

Write-Host ""
Write-Host "[3/3] 检查配置文件..." -ForegroundColor Cyan

if (-not (Test-Path "config\hub.yaml")) {
    Write-Host "[警告] 未找到 config\hub.yaml" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "如未初始化，请先运行:" -ForegroundColor Yellow
    Write-Host "  python scripts\init_hub.py" -ForegroundColor White
    Write-Host ""
    
    $continue = Read-Host "是否继续启动？(y/n)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 1
    }
} else {
    Write-Host "[✓] 配置文件存在" -ForegroundColor Green
}

Write-Host ""
Write-Host "[4/3] 启动 Web UI..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 浏览器访问地址: http://127.0.0.1:7860" -ForegroundColor Green
Write-Host ""
Write-Host "💡 提示:" -ForegroundColor Yellow
Write-Host "   - 按 Ctrl+C 可停止服务" -ForegroundColor Gray
Write-Host "   - 如遇问题请查看下方错误信息" -ForegroundColor Gray
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 启动 Web UI
streamlit run streamlit_app.py --server.port 7860 --server.address 127.0.0.1

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "[错误] Web UI 启动失败！" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "常见原因及解决方案：" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. 端口被占用" -ForegroundColor White
    Write-Host "   解决: 编辑 web_ui.py，修改 server_port 为其他值" -ForegroundColor Gray
    Write-Host ""
    Write-Host "2. 配置文件错误" -ForegroundColor White
    Write-Host "   解决: 检查 config\hub.yaml 格式是否正确" -ForegroundColor Gray
    Write-Host ""
    Write-Host "3. 数据库文件损坏" -ForegroundColor White
    Write-Host "   解决: 重新运行 python scripts\init_hub.py" -ForegroundColor Gray
    Write-Host ""
    Write-Host "4. 依赖版本冲突" -ForegroundColor White
    Write-Host "   解决: 运行 pip install -r requirements.txt --upgrade" -ForegroundColor Gray
    Write-Host ""
    
    Read-Host "按回车退出"
}
