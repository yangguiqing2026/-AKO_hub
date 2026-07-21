# Web UI Agent 下拉选择功能说明

## 功能概述

AKO Hub Web UI 现已支持从注册表动态加载 Agent 和 Workflow 列表，提供便捷的下拉选择功能，同时支持自定义输入。

## 主要改进

### 1. 执行任务标签页增强

**原有方式：**
- Agent 名称和工作流 ID 使用文本框（Textbox）手动输入
- 需要用户记忆准确的 Agent 名称或工作流 ID

**新方式：**
- ✅ Agent 名称改为下拉列表（Dropdown），自动显示已注册的 Agent
- ✅ 工作流 ID 改为下拉列表，自动显示已注册的 Workflow
- ✅ 支持 `allow_custom_value=True`，可以输入注册表中不存在的新 Agent/Workflow
- ✅ 留空时系统自动路由和分配

### 2. 管理 Agent 标签页（新增）

新增了专门的 Agent 管理界面，包含两个功能区域：

#### 2.1 查看已注册 Agent 列表

- 以表格形式展示所有已注册的 Agent
- 显示字段：名称、类型、工作流 ID、状态、描述
- 点击"刷新列表"按钮可重新加载注册表数据
- 页面加载时自动刷新显示

#### 2.2 注册新 Agent

提供表单界面用于生成新 Agent 的注册代码：

**必填字段：**
- Agent 名称：Agent 的显示名称
- 工作流 ID：唯一的工作流标识符（如 `wf_new_agent`）
- Python 模块路径：Agent 代码所在的模块（如 `agents.new_agent`）

**可选字段：**
- 入口函数：默认为 `run`，LangGraph 子图可留空
- 描述：Agent 的功能说明

**使用流程：**
1. 填写表单信息
2. 点击"注册 Agent"按钮
3. 复制生成的代码片段
4. 将代码添加到 `registry/workflows.py` 的 `SPOKE_REGISTRY` 列表中
5. 重启 Web UI 即可在下拉列表中看到新 Agent

## 技术实现

### 核心函数

```python
def get_agent_choices() -> List[str]:
    """从注册表中获取所有已注册的 Agent 名称列表。"""
    agents = list_spokes_by_type("agent")
    return [agent["name"] for agent in agents if agent.get("status") == "registered"]


def get_workflow_choices() -> List[str]:
    """从注册表中获取所有已注册的工作流 ID 列表。"""
    workflows = list_spokes_by_type("workflow")
    return [wf["workflow_id"] for wf in workflows if wf.get("status") == "registered"]
```

### 数据来源

- 从 `registry.workflows` 模块导入 `SPOKE_REGISTRY` 注册表
- 使用 `list_spokes_by_type()` 函数按类型过滤
- 仅显示状态为 `"registered"` 的条目

### 界面组件

```python
agent_dropdown = gr.Dropdown(
    label="Agent 名称（可选）",
    choices=get_agent_choices(),  # 动态加载
    value=None,
    allow_custom_value=True,      # 支持自定义输入
    info="从注册表选择或输入自定义 Agent 名称"
)
```

## 使用示例

### 示例 1：选择已注册 Agent

1. 进入"🚀 执行任务"标签页
2. 在"Agent 名称"下拉框中点击
3. 从列表中选择，如"建筑结构设计 Agent"
4. 填写其他必填项后提交任务

### 示例 2：使用自定义 Agent

1. 在"Agent 名称"下拉框中直接输入新名称
2. 例如输入："我的自定义 Agent"
3. 系统会接受该值并提交任务
4. 如需永久注册，使用"⚙️ 管理 Agent"标签页生成注册代码

### 示例 3：注册新 Agent

1. 进入"⚙️ 管理 Agent"标签页
2. 填写新 Agent 信息：
   - Agent 名称：结构优化 Agent
   - 工作流 ID：wf_structural_optimizer
   - Python 模块路径：agents.structural_optimizer
   - 入口函数：run
   - 描述：自动优化结构设计方案
3. 点击"注册 Agent"按钮
4. 复制生成的代码片段
5. 编辑 `registry/workflows.py`，将代码添加到 `SPOKE_REGISTRY` 列表
6. 重启 Web UI

## 当前注册的 Agent 列表

根据 `registry/workflows.py`，当前已注册以下 Agent：

1. **建筑结构设计 Agent** (`wf_ako_architect`)
   - 结构计算、方案设计、技术文档生成

2. **图纸质检 Agent-01/02/03** (`wf_ako_inspector_01/02/03`)
   - 图纸规范检查、标注审查

3. **图像分析 Agent-01/02/03** (`wf_ako_analyzer_01/02/03`)
   - 施工现场图像分析、缺陷识别

以及 1 个工作流：
- **AKO 主工作流** (`wf_ako_main`)

## 注意事项

1. **自定义 Agent 的持久化**：通过下拉框输入的自定义 Agent 名称仅在当次会话有效，如需永久使用，必须添加到注册表
2. **注册表修改后需重启**：修改 `registry/workflows.py` 后，需要重启 Web UI 才能在下拉列表中看到更新
3. **状态过滤**：只有状态为 `"registered"` 的 Agent 才会显示在下拉列表中
4. **向后兼容**：原有的 API 接口保持不变，仍然支持通过 `hub_api.submit_task()` 传递任意 Agent 名称

## 未来扩展

可能的增强方向：
- [ ] 支持在线编辑注册表并自动保存
- [ ] 支持启用/禁用 Agent（修改 status 字段）
- [ ] 支持删除已注册的 Agent
- [ ] 添加 Agent 测试功能
- [ ] 支持批量导入/导出注册表

---

**文档版本**: v1.0  
**最后更新**: 2026-06-19  
**维护者**: AKO Hub 开发团队
