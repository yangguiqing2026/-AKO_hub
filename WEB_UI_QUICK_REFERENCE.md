# 🚀 Web UI 启动 - 快速参考卡

## ⚡ 30秒快速启动

```bash
# 方法1: 自动修复（推荐）
python fix_web_ui.py

# 方法2: 直接启动
start_web_ui.bat

# 方法3: PowerShell
.\start_web_ui.ps1
```

访问：**http://127.0.0.1:7860**

---

## 🔧 遇到问题？

### ❌ 缺少依赖
```bash
pip install gradio>=4.0.0
```

### ❌ 配置缺失
```bash
python scripts/init_hub.py
```

### ❌ 端口占用
```bash
# 查看占用
netstat -ano | findstr :7860

# 或修改 web_ui.py 中的端口号
```

### ❌ 其他问题
```bash
python diagnose_web_ui.py
```

---

## 📚 文档速查

- **快速修复**: `WEB_UI_QUICK_FIX.md`
- **详细排查**: `WEB_UI_TROUBLESHOOTING.md`
- **功能说明**: `WEB_UI_README.md`
- **解决方案总结**: `WEB_UI_FIX_SUMMARY.md`

---

## 💡 常用命令

```bash
# 诊断系统
python diagnose_web_ui.py

# 自动修复
python fix_web_ui.py

# 更新依赖
pip install -r requirements.txt --upgrade

# 检查端口
netstat -ano | findstr :7860

# 查看 Python 版本
python --version

# 查看已安装包
pip list | findstr gradio
```

---

## ✅ 成功标志

看到以下输出即成功：
```
* Running on local URL:  http://127.0.0.1:7860
```

---

**保存此卡片以便快速查阅！**
