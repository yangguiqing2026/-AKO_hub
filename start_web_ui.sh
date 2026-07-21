#!/bin/bash
# AKO Hub Web UI 快速启动脚本
# 用于 Linux/Mac 环境下快速启动 Gradio 界面

echo "========================================"
echo "  AKO Hub Web UI 启动脚本"
echo "========================================"
echo ""

# 检查 Python 是否安装
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.8+"
    exit 1
fi

echo "[1/3] 检查依赖包..."
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "[提示] 检测到 streamlit 未安装，正在安装..."
    pip3 install streamlit>=1.28.0
    if [ $? -ne 0 ]; then
        echo "[错误] 依赖安装失败，请检查网络连接或手动运行: pip3 install streamlit>=1.28.0"
        exit 1
    fi
    echo "[成功] 依赖安装完成"
else
    echo "[成功] streamlit 已安装"
fi

echo ""
echo "[2/3] 检查配置文件..."
if [ ! -f "config/hub.yaml" ]; then
    echo "[警告] 未找到 config/hub.yaml，请确保已完成初始化"
    echo "        如未初始化，请运行: python3 scripts/init_hub.py"
    read -p "按回车继续..."
fi

echo ""
echo "[3/3] 启动 Web UI..."
echo "========================================"
echo ""
echo "浏览器访问地址: http://127.0.0.1:7860"
echo ""
echo "按 Ctrl+C 可停止服务"
echo "========================================"
echo ""

streamlit run streamlit_app.py --server.port 7860 --server.address 127.0.0.1
