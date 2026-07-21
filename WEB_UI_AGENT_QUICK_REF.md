# Web UI Agent 选择 - 快速参考

## 🎯 核心功能

### 执行任务时选择 Agent
- **下拉列表**：自动显示已注册的 7 个 Agent
- **自定义输入**：可直接输入新的 Agent 名称
- **智能留空**：不选择时系统自动分配

### 管理 Agent
- **查看列表**：浏览所有已注册 Agent 的详细信息
- **注册新 Agent**：生成注册代码，一键添加到系统

---

## 📋 当前可用 Agent

| Agent 名称 | 工作流 ID | 功能 |
|-----------|----------|------|
| 建筑结构设计 Agent | wf_ako_architect | 结构计算、方案设计 |
| 图纸质检 Agent-01 | wf_ako_inspector_01 | 图纸规范检查 |
| 图纸质检 Agent-02 | wf_ako_inspector_02 | 图纸规范检查 |
| 图纸质检 Agent-03 | wf_ako_inspector_03 | 图纸规范检查 |
| 图像分析 Agent-01 | wf_ako_analyzer_01 | 图像分析、缺陷识别 |
| 图像分析 Agent-02 | wf_ako_analyzer_02 | 图像分析、缺陷识别 |
| 图像分析 Agent-03 | wf_ako_analyzer_03 | 图像分析、缺陷识别 |

---

## ⚡ 快速操作

### 使用已有 Agent
```
1. 打开"🚀 执行任务"标签页
2. 点击"Agent 名称"下拉框
3. 选择需要的 Agent
4. 填写其他信息并提交
```

### 注册新 Agent
```
1. 打开"⚙️ 管理 Agent"标签页
2. 填写新 Agent 信息（名称、ID、模块路径）
3. 点击"注册 Agent"按钮
4. 复制生成的代码
5. 粘贴到 registry/workflows.py
6. 重启 Web UI
```

---

## 💡 提示

- ✅ 下拉列表支持搜索过滤
- ✅ 可以输入注册表中不存在的 Agent 名称
- ✅ 修改注册表后需重启 Web UI
- ✅ 详细文档见 `WEB_UI_AGENT_SELECTION.md`

---

**最后更新**: 2026-06-19
