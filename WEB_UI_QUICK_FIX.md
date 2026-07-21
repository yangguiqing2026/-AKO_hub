# AKO Hub Web UI 启动问题 - 快速解决指南

## 🚨 问题：Web UI 无法开启

别担心！我们提供了多种工具来帮助您快速解决问题。

---

## ⚡ 最快解决方案（3步搞定）

### 方法 1：使用自动修复工具（推荐）

```bash
python fix_web_ui.py
```

这个脚本会：
- ✅ 自动检查 Python 环境
- ✅ 安装/更新所有依赖包
- ✅ 检查配置文件
- ✅ 检查数据库文件
- ✅ 检测端口占用
- ✅ 可选直接启动 Web UI

### 方法 2：使用诊断工具

```bash
python diagnose_web_ui.py
```

这个脚本会提供详细的系统状态报告，帮助您定位问题。

### 方法 3：查看详细排查指南

打开文件：**WEB_UI_TROUBLESHOOTING.md**

包含所有常见问题的详细解决方案。

---

## 🔧 常见问题及快速修复

### 问题 1：提示 "No module named 'gradio'"

**原因**：缺少 gradio 依赖包

**解决**：
```bash
pip install gradio>=4.0.0
```

或使用自动修复：
```bash
python fix_web_ui.py
```

### 问题 2：提示 "config/hub.yaml not found"

**原因**：配置文件不存在

**解决**：
```bash
python scripts/init_hub.py
```

### 问题 3：提示 "Address already in use" 或端口被占用

**原因**：端口 7860 已被其他程序占用

**解决方式 A**：关闭占用端口的程序

**解决方式 B**：修改端口号
1. 编辑 `web_ui.py`
2. 找到最后一行：`server_port=7860`
3. 改为：`server_port=7861`（或其他未被占用的端口）

### 问题 4：启动后浏览器无法访问

**检查清单**：
1. 确认服务已启动（命令行显示 "Running on local URL"）
2. 确认防火墙未阻止 7860 端口
3. 尝试访问 http://localhost:7860 或 http://127.0.0.1:7860
4. 检查是否有错误信息输出

### 问题 5：导入错误或其他 Python 错误

**解决**：重新安装所有依赖
```bash
pip install -r requirements.txt --upgrade
```

然后重新初始化：
```bash
python scripts/init_hub.py
```

### 问题 6：提示 "Textbox.__init__() got an unexpected keyword argument 'show_copy_button'"

**原因**：Gradio 版本兼容性问题

**解决**：
```bash
# 升级 Gradio 到最新版本
pip install gradio>=4.0.0 --upgrade
```

或者直接使用已修复的代码（我们已移除不兼容参数）。

---

## 📋 三种启动方式

### 方式 1：批处理脚本（Windows，最简单）
```bash
start_web_ui.bat
```
特点：自动检查依赖、友好的错误提示

### 方式 2：PowerShell 脚本（Windows）
```powershell
.\start_web_ui.ps1
```
特点：彩色输出、更详细的检查

### 方式 3：直接运行（通用）
```bash
python web_ui.py
```
特点：最直接，适合调试

---

## 🎯 成功启动的标志

当您看到以下输出时，表示启动成功：

```
============================================================
🎯 AKO Hub Web UI 启动中...
============================================================
📖 文档: README.md / WEB_UI_README.md
🔗 访问地址: http://127.0.0.1:7860
============================================================

* Running on local URL:  http://127.0.0.1:7860
* To create a public link, set `share=True` in `launch()`.
```

此时在浏览器中打开 **http://127.0.0.1:7860** 即可看到控制面板。

---

## 🆘 仍然无法解决？

请收集以下信息，以便获取帮助：

1. **Python 版本**
   ```bash
   python --version
   ```

2. **已安装的包**
   ```bash
   pip list | findstr gradio
   ```

3. **完整错误信息**
   复制运行 `python web_ui.py` 时的所有输出

4. **诊断报告**
   ```bash
   python diagnose_web_ui.py > diagnosis.txt
   ```
   将生成的 `diagnosis.txt` 文件内容发送给我们

5. **操作系统信息**
   - Windows 版本
   - 是否使用管理员权限运行

---

## 📚 相关文档

- [WEB_UI_README.md](WEB_UI_README.md) - Web UI 功能详细说明
- [WEB_UI_TROUBLESHOOTING.md](WEB_UI_TROUBLESHOOTING.md) - 完整故障排查指南
- [README.md](README.md) - 项目总体说明
- [INSTALL_GUIDE.md](INSTALL_GUIDE.md) - 安装指南

---

## 💡 小贴士

1. **首次使用**：建议先运行 `python fix_web_ui.py` 进行自动修复
2. **定期维护**：偶尔运行一次 `pip install -r requirements.txt --upgrade` 保持依赖最新
3. **端口冲突**：如果经常遇到端口占用，可以固定修改为一个不常用的端口
4. **备份配置**：修改 `web_ui.py` 前建议备份原文件

---

**祝您使用愉快！** 🎉
