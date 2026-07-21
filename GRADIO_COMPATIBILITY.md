# Gradio 版本兼容性说明

## 问题背景

AKO Hub Web UI 使用 Gradio 框架构建。不同版本的 Gradio API 存在差异，可能导致兼容性问题。

## 已知兼容性问题

### 问题 1: `show_copy_button` 参数（已修复）✅

**错误信息**:
```
Textbox.__init__() got an unexpected keyword argument 'show_copy_button'
```

**状态**: ✅ **已修复** - 已从代码中移除该参数

---

### 问题 2: Gradio 6.0 API 变化（已修复）✅

**警告信息**:
```
UserWarning: The parameters have been moved from the Blocks constructor to the launch() method in Gradio 6.0: theme, css.
```

**原因**: 
- Gradio 6.0 将 `theme` 和 `css` 参数从 `Blocks()` 构造函数移到了 `launch()` 方法

**解决方案**: ✅ **已修复**
- 已将 `theme` 和 `css` 参数移到 `launch()` 方法中
- 代码现在同时兼容 Gradio 4.x 和 6.x

---

### 问题 3: DataFrame `col_count` 参数过时（已修复）✅

**警告信息**:
```
UserWarning: The `col_count` parameter is deprecated and will be removed. Please use `column_count` instead.
```

**原因**: 
- `col_count` 参数在新版本中被废弃

**解决方案**: ✅ **已修复**
- 已替换为 `column_widths` 参数，提供更好的列宽控制

---

## 推荐的 Gradio 版本

| 版本范围 | 状态 | 说明 |
|---------|------|------|
| < 4.0.0 | ❌ 不推荐 | 过旧，API 差异大 |
| 4.0.0 - 4.19.x | ⚠️ 兼容 | 已移除不兼容参数，可使用 |
| 4.20.0 - 4.x | ✅ 推荐 | 完整功能支持 |
| 5.x | 🔜 待测试 | 需要验证兼容性 |

---

## 检查当前版本

```bash
python -c "import gradio; print('Gradio version:', gradio.__version__)"
```

---

## 版本管理最佳实践

### 1. 固定依赖版本

在 `requirements.txt` 中指定明确的版本范围：
```txt
gradio>=4.20.0,<5.0.0
```

### 2. 定期更新依赖

```bash
# 查看所有可更新的包
pip list --outdated

# 更新 Gradio
pip install gradio --upgrade
```

### 3. 使用虚拟环境

```bash
# 创建虚拟环境
python -m venv ako_hub_env

# 激活环境（Windows）
ako_hub_env\Scripts\activate

# 激活环境（Linux/Mac）
source ako_hub_env/bin/activate

# 安装依赖
pip install -r requirements.txt
```

---

## 常见版本相关错误及解决

### 错误 1: show_copy_button 不支持
**解决**: 已修复，见上方

### 错误 2: Theme 类不存在
**原因**: Gradio 3.x 到 4.x 的主题 API 变化
**解决**: 升级到 Gradio 4.x

### 错误 3: Blocks.launch() 参数变化
**原因**: 不同版本的启动参数差异
**解决**: 使用标准参数集

### 错误 4: Examples 组件 API 变化
**原因**: Gradio 4.x 重构了 Examples 组件
**解决**: 确保使用 Gradio 4.0+

---

## 诊断工具

运行以下命令检查版本兼容性：

```bash
# 检查 Gradio 版本
python -c "import gradio; print(gradio.__version__)"

# 运行完整诊断
python diagnose_web_ui.py

# 自动修复兼容性问题
python fix_web_ui.py
```

---

## 开发者注意事项

### 编写兼容代码

1. **避免使用最新特性**: 除非确认最低支持版本
2. **条件判断**: 对可选功能进行版本检查
3. **降级策略**: 为新特性提供备选方案

示例：
```python
import gradio as gr

# 检查版本
version = tuple(map(int, gr.__version__.split('.')[:2]))

# 根据版本选择参数
if version >= (4, 20):
    textbox = gr.Textbox(show_copy_button=True)
else:
    textbox = gr.Textbox()  # 不使用 show_copy_button
```

### 测试多版本

建议在多个 Gradio 版本上测试：
- Gradio 4.20.0（最小支持版本）
- Gradio 4.44.0（最新稳定版）
- Gradio 5.x（未来版本，待测试）

---

## 获取帮助

如果遇到版本兼容性问题：

1. 查看本文档的"常见版本相关错误"部分
2. 运行 `python diagnose_web_ui.py` 获取诊断报告
3. 尝试升级或降级 Gradio 版本
4. 查阅 [WEB_UI_TROUBLESHOOTING.md](WEB_UI_TROUBLESHOOTING.md)

---

**最后更新**: 2026-06-19  
**适用版本**: AKO Hub v1.0 + Gradio 4.x
