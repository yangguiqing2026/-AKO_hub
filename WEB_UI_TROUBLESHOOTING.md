# AKO Hub Web UI 故障排查指南

## 问题：Web UI 无法开启

请按照以下步骤逐一排查：

### 步骤 1：检查 Python 环境

打开命令行（PowerShell 或 CMD），运行：
```bash
python --version
```

应该显示 Python 3.8 或更高版本。如果提示找不到 python，请先安装 Python。

### 步骤 2：检查 gradio 依赖

运行诊断脚本：
```bash
python diagnose_web_ui.py
```

或者手动检查：
```bash
python -c "import gradio; print('Gradio version:', gradio.__version__)"
```

**如果 gradio 未安装**，运行：
```bash
pip install gradio>=4.0.0
```

### 步骤 3：检查配置文件

确认 `config/hub.yaml` 文件存在。如果不存在，运行初始化脚本：
```bash
python scripts/init_hub.py
```

### 步骤 4：检查端口占用

检查端口 7860 是否被占用：

**Windows:**
```bash
netstat -ano | findstr :7860
```

**如果端口被占用**，有两种解决方案：
1. 关闭占用端口的程序
2. 编辑 `web_ui.py`，修改最后一行的 `server_port=7860` 为其他端口（如 7861）

### 步骤 5：查看详细错误信息

尝试启动并查看完整错误输出：
```bash
python web_ui.py
```

将错误信息复制下来，常见错误及解决方案：

#### 错误 1：ModuleNotFoundError: No module named 'gradio'
**解决**: `pip install gradio>=4.0.0`

#### 错误 2：FileNotFoundError: config/hub.yaml
**解决**: `python scripts/init_hub.py`

#### 错误 3：OSError: [Errno 98] Address already in use
**解决**: 端口被占用，见步骤 4

#### 错误 4：ImportError: cannot import name 'xxx' from 'hub_api'
**解决**: 检查 hub_api.py 和相关依赖是否正确安装

#### 错误 5：sqlite3.OperationalError
**解决**: 数据库文件损坏，重新运行 `python scripts/init_hub.py`

#### 错误 6：Textbox.__init__() got an unexpected keyword argument 'show_copy_button'

**原因**: Gradio 版本兼容性问题。`show_copy_button` 参数在 Gradio 4.x 早期版本中不存在。

**解决**: 

**方案 A（推荐）**: 升级 Gradio 到最新版本
```bash
pip install gradio>=4.0.0 --upgrade
```

**方案 B**: 代码已自动修复
- 我们已移除了不兼容的参数
- 直接运行即可：`python web_ui.py`

**方案 C**: 手动降级到稳定版本
```bash
pip install gradio==4.44.0
```

---

### 步骤 6：使用批处理脚本启动

双击运行：
```
start_web_ui.bat
```

这个脚本会自动检查依赖并给出详细错误提示。

### 步骤 7：重置环境（终极方案）

如果以上都不行，尝试重置：

```bash
# 1. 重新安装所有依赖
pip install -r requirements.txt --upgrade

# 2. 重新初始化（注意：这会重置数据库）
python scripts/init_hub.py

# 3. 再次尝试启动
python web_ui.py
```

---

## 获取帮助

如果问题仍未解决，请提供以下信息：

1. **Python 版本**: `python --version`
2. **已安装的包**: `pip list | findstr gradio`
3. **完整错误信息**: 运行 `python web_ui.py` 的输出
4. **操作系统**: Windows/Linux/MacOS
5. **诊断脚本输出**: `python diagnose_web_ui.py` 的完整输出

---

## 快速启动命令

```bash
# 方式 1: 直接运行
python web_ui.py

# 方式 2: 使用批处理脚本（推荐）
start_web_ui.bat

# 方式 3: 先诊断再启动
python diagnose_web_ui.py
python web_ui.py
```

访问地址：**http://127.0.0.1:7860**
