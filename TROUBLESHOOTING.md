# Web UI 启动问题快速修复指南

## 🚨 常见问题及解决方案

### 问题 1: ModuleNotFoundError: No module named 'gradio'

**症状**: 启动时提示找不到 gradio 模块

**原因**: gradio 依赖未安装

**解决方案**（任选其一）:

#### 方案 A: 使用一键修复脚本（推荐）
```bash
双击运行: fix_and_start.bat
```

#### 方案 B: 手动安装
```bash
pip install gradio>=4.0.0
```

#### 方案 C: 安装所有依赖
```bash
pip install -r requirements.txt
```

#### 方案 D: 使用国内镜像源（网络慢时）
```bash
pip install gradio>=4.0.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

### 问题 2: 端口 7860 被占用

**症状**: 
```
OSError: [Errno 98] Address already in use
```

**解决方案**:

#### 方案 A: 修改端口号
编辑 `web_ui.py` 最后一行：
```python
server_port=7861  # 改为其他端口，如 7861, 8080, 9000
```

#### 方案 B: 关闭占用程序
```bash
# Windows 查找占用端口的进程
netstat -ano | findstr :7860

# 然后杀死进程（替换 PID）
taskkill /F /PID <PID>
```

---

### 问题 3: 配置文件不存在

**症状**: 
```
FileNotFoundError: config/hub.yaml
```

**解决方案**:
```bash
python scripts/init_hub.py
```

---

### 问题 4: 数据库文件损坏

**症状**: 
```
sqlite3.DatabaseError 或类似错误
```

**解决方案**:
```bash
# 重新初始化
python scripts/init_hub.py
```

---

### 问题 5: Python 版本过低

**症状**: 
```
SyntaxError 或 ImportError
```

**解决方案**:
1. 检查版本: `python --version`
2. 需要 Python 3.8+
3. 下载地址: https://www.python.org/downloads/

---

## 🔧 快速诊断

运行诊断脚本自动检测问题：

```bash
python diagnose.py
```

诊断脚本会检查：
- ✓ Python 环境
- ✓ Gradio 依赖
- ✓ 配置文件
- ✓ 数据库文件
- ✓ 端口占用
- ✓ API 模块

---

## 🚀 标准启动流程

### 首次启动
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化（如果还没初始化）
python scripts/init_hub.py

# 3. 启动 Web UI
python web_ui.py
```

### 日常启动
```bash
# 方式 1: 使用启动脚本
start_web_ui.bat

# 方式 2: 直接运行
python web_ui.py
```

---

## 💡 常见错误代码速查

| 错误代码 | 含义 | 解决方法 |
|---------|------|---------|
| ModuleNotFoundError | 模块未安装 | `pip install <模块名>` |
| OSError: Address already in use | 端口被占用 | 修改端口或关闭占用程序 |
| FileNotFoundError | 文件不存在 | 检查路径或重新初始化 |
| PermissionError | 权限不足 | 以管理员身份运行 |
| ImportError | 导入失败 | 检查依赖版本兼容性 |

---

## 📞 仍然无法解决？

### 步骤 1: 运行诊断
```bash
python diagnose.py
```

### 步骤 2: 查看详细错误
```bash
python web_ui.py 2>&1 | tee error.log
```

### 步骤 3: 收集信息
- Python 版本: `python --version`
- pip 版本: `pip --version`
- 操作系统: Windows/Linux/Mac
- 错误日志: 复制完整错误信息

### 步骤 4: 联系技术支持
提供以上信息给AKO技术团队

---

## ✅ 验证是否修复成功

启动后应该看到：
```
============================================================
🎯 AKO Hub Web UI 启动中...
============================================================
📖 文档: README.md / WEB_UI_README.md
🔗 访问地址: http://127.0.0.1:7860
============================================================
Running on local URL:  http://127.0.0.1:7860
```

然后在浏览器访问 http://127.0.0.1:7860 能看到界面。

---

**祝您顺利解决问题！** 🎉
