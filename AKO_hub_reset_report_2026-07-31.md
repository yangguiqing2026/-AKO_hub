# AKO_hub 启动前清零报告

> **执行时间**：2026-07-31  
> **执行人**：AKO_studio（脚本）  
> **目标**：清除 Web/GUI 时代全部残留，转为纯 CLI Agent 调度中枢

---

## 一、配置文件清理

| 操作 | 状态 |
|------|------|
| 删除 Web 服务器配置 | ✅ 原配置无 server/ui/streamlit/gradio/web_routes 块，无需删除 |
| 删除 GUI 配置 | ✅ 原配置无 GUI 相关块 |
| 保留 Agent 调度配置 | ✅ 已写入 v2.0 完整配置（registry/routing/health_check/message_queue/logging/storage） |
| 旧配置备份 | ✅ 已备份到 `config/backup/AKO_hub_config_v1.x_web.yaml` |

---

## 二、数据文件清理

| 文件/目录 | 操作 | 状态 |
|-----------|------|------|
| data/web_routes.json | 删除 | ✅ 原本不存在 |
| data/web_routes.yaml | 删除 | ✅ 原本不存在 |
| data/agent_registry.json | 删除 | ✅ 原本不存在 |
| data/agent_registry.db | 删除 | ✅ 原本不存在 |
| data/routing_table.json | 重建为空 | ✅ 已创建 v2.0.0 空路由表 |
| data/agent_state.json | 重建为空 | ✅ 已创建 v2.0.0 空状态文件 |
| logs/*.log | 删除 | ✅ 已清除旧日志 |
| logs/hub.log | 新建空文件 | ✅ 已创建 |

---

## 三、代码残留清理

| 文件 | 扫描模式 | 处理方式 | 状态 |
|------|----------|----------|------|
| `heartbeat/heartbeat_receiver.py` | Flask Blueprint | 移除 Blueprint/路由/Response，保留核心心跳函数（receive_heartbeat_data, get_agents_status, _upsert_agent_registry, _insert_heartbeat） | ✅ |
| `agents/knowledge_service.py` | FastAPI serve() | 移除 serve() 函数和 --serve 分支，保留 stdin JSON 处理 | ✅ |
| `agents/ako_knowledge_adapter.py` | uvicorn.run / server action | 移除 action=="server" 分支，保留 search/health | ✅ |
| `router/task_executor.py` | fastapi type + _call_spoke_http | SPOKE_REGISTRY 全部改为 "type":"script"，入口改为 adapter 文件；移除 _call_spoke_http 方法；修复 subprocess.run 注释 | ✅ |
| `src/` 目录 | flask/fastapi/streamlit/gradio | 0 残留 | ✅ |

**汇总统计：**

| 扫描模式 | 发现数量 | 处理数量 | 状态 |
|----------|----------|----------|------|
| flask import/usage | 8 处 | 8 处 | ✅ |
| fastapi import/usage | 6 处 | 6 处 | ✅ |
| streamlit import | 0 处 | 0 处 | ✅ |
| gradio import | 0 处 | 0 处 | ✅ |
| uvicorn.run | 2 处 | 2 处 | ✅ |
| 其他 GUI 框架 | 0 处 | 0 处 | ✅ |

> 注：`archive/gui_deprecated/` 中的残留为已归档代码，不在清理范围内。

---

## 四、目录清理

| 目录 | 操作 | 状态 |
|------|------|------|
| .streamlit/ | 删除 | ✅ |
| .gradio/ | 删除 | ✅ |
| templates/ | 检查 | ✅ 不存在 |
| static/ | 检查 | ✅ 不存在 |
| streamlit_pages/ | 检查 | ✅ 不存在 |
| gui/ | 检查 | ✅ 不存在 |
| web_ui/ | 检查 | ✅ 不存在 |
| __pycache__/ | 检查 | ✅ 无残留 |

> 注：`archive/gui_deprecated/` 已存在，旧 Web 代码已归档。

---

## 五、依赖清理

| 操作 | 状态 |
|------|------|
| 删除 Web/GUI 依赖 | ✅ 已移除 gradio/fastapi/uvicorn/streamlit 注释行，清理 requirements.txt |
| 保留核心依赖 | ✅ 保留 langgraph/chromadb/pyyaml/requests/pydantic/pandas/ollama 等 15 项核心依赖 |
| 新增核心依赖 | ✅ 补充 python-json-logger>=2.0.0, websocket-client>=1.4.0 |

---

## 六、环境变量清理

| 操作 | 状态 |
|------|------|
| 检查 .env 文件 | ✅ 不存在 .env 文件，无需清理 |
| 检查 secrets.env | ✅ 不存在 |
| 检查 .env.template | ✅ 无 FLASK/FASTAPI/STREAMLIT/GRADIO 相关变量 |

---

## 七、验证结果

| 验证项 | 结果 |
|--------|------|
| 代码纯净度扫描（src/） | ✅ 0 残留 |
| 代码纯净度扫描（全项目活跃代码） | ✅ 0 残留（仅 archive/ 有已归档残留） |
| 目录纯净度检查 | ✅ 通过 |
| 路由表为空 | ✅ `data/routing_table.json` agents:{}, routes:{} |
| 配置文件版本 | ✅ v2.0.0 |

---

## 八、总体状态

**✅ 清零完成**

AKO_hub 已从 Web 界面总调度改造为纯 CLI Agent 调度中枢，所有 Web/GUI 时代残留已清除。

---

## 九、遗留问题

| 问题 | 建议 |
|------|------|
| 无 | — |

---

> **下一步**：执行启动验证，确认无 Web 服务器输出。
