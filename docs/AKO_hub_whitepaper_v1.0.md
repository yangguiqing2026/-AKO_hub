---
agent_id: "AKO_hub"
name: "总线调度 Agent"
version: "2.0.0"
author: "AKO_studio"
date: "2026-07-31"
status: "active"
tags:
  - "infrastructure"
  - "agent"
  - "hub"
---

# 总线调度 Agent 白皮书 v2.0.0

> **Agent ID**: AKO_hub  
> **版本**: v2.0.0  
> **作者**: AKO_studio  
> **日期**: 2026-07-31  
> **状态**: active

---

## 一、概述

### 1.1 定位
AKO Hub 是 AKO 智能体体系的总线调度中枢，负责 Agent 注册发现、意图路由、工作流编排与健康巡检。

### 1.2 目标
在 AKO 体系中作为中心调度节点，通过 CLI/配置驱动方式管理 31 个 Spoke Agent 的全生命周期调度。

### 1.3 适用范围
- **适用场景**：AKO 舰队内部调度与协作、Agent 注册同步、意图路由、工作流编排
- **不适用场景**：独立运行的 GUI 应用（已有 Streamlit Web UI :7860 覆盖）

### 1.4 与 AKO 体系的关系
- 上游依赖：AKO_registry_agent（注册中心）
- 下游服务：31 个 Spoke Agent（建筑、设计、质检、商业、营销等全部业务 Agent）
- 在 pipeline 中的位置：总控调度层

---

## 二、功能规格

### 2.1 核心能力

| 能力编号 | 能力名称 | 描述 | 输入 | 输出 | 触发方式 |
|----------|----------|------|------|------|----------|
| C001 | Agent 注册与发现 | 从 registry_agent 同步 Agent 信息到路由表 | registry_endpoint | routing_table.json (32 Agent) | CLI --sync-registry |
| C002 | 意图路由 | 18 关键词 + 5 复合任务匹配，Kahn DAG 拓扑排序 | 自然语言意图 | 目标 Agent ID + entry_module | CLI --route / importlib |
| C003 | 工作流编排 | LangGraph Master Graph 7 节点编排（路由→知识库分配→调用→文件采集→同步监控→错误处理→状态聚合） | MasterState | 任务完成状态 + generated_files | CLI dispatch / Web UI |
| C004 | 健康巡检 | 31 Spoke Agent 心跳监控，对比注册中心与路由表差异 | 路由表 + 注册中心数据 | 在线/离线/缺失统计 | CLI health-check |
| C005 | 双模式调度 | importlib 直调（低延迟）+ subprocess 子进程（进程级隔离，stdin→stdout JSON，300s 超时） | payload | Spoke 执行结果 | CLI / Web UI |

### 2.2 接口规范

#### CLI 接口
```bash
python src/core/main.py --config config/AKO_hub_config.yaml [选项]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --config | string | 是 | - | 配置文件路径 |
| --log-level | string | 否 | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| --sync-registry | flag | 否 | - | 从注册中心同步 Agent 路由表 |
| --status | flag | 否 | - | 显示路由表状态 |
| --route INTENT | string | 否 | - | 按意图路由到目标 Agent |
| --route-to AGENT_ID | string | 否 | - | 直连指定 Agent |

#### 子命令
| 命令 | 说明 |
|------|------|
| dispatch AGENT_ID [--test] | 向指定 Agent 派发任务 |
| health-check | 巡检全部 Agent 健康状态 |

#### 配置文件接口
`config/AKO_hub_config.yaml` 包含运行所需全部参数（agent/registry/routing/health_check/message_queue/logging/storage）。

#### 输出接口
- 路由表：`data/routing_table.json`（32 Agent 完整路由信息）
- Agent 状态：`data/agent_state.json`
- 日志：`logs/hub.log`（滚动日志，10MB × 5 份备份）

### 2.3 依赖清单

| 依赖 | 版本 | 用途 | 是否可替代 |
|------|------|------|-----------|
| langgraph | >=0.0.40 | Master Graph 状态机编排 | 否 |
| chromadb | >=0.4.22 | 知识库向量存储（通过 KnowledgeHub） | 否 |
| pyyaml | >=6.0 | 配置文件解析 | 否 |
| gradio | >=4.20.0 | Web UI（已有 Streamlit 替代方案） | 是 |
| fastapi | >=0.100.0 | API 服务（hub_api.py） | 否 |
| uvicorn | >=0.20.0 | ASGI 服务器 | 否 |
| streamlit | >=1.30.0 | Web UI 主框架 | 否 |
| pandas | >=2.0 | 数据处理 | 是 |
| requests | >=2.28.0 | HTTP 远程注册中心拉取 | 否 |

---

## 三、架构设计

### 3.1 模块结构

```
AKO_hub/
├── src/
│   ├── core/
│   │   ├── main.py              # CLI 入口（--sync-registry / --status / dispatch / health-check）
│   │   ├── config_loader.py     # 配置加载（YAML → HubConfig 对象）
│   │   ├── registry_client.py   # 注册中心客户端（HTTP + 本地 fallback）
│   │   ├── routing_table.py     # 路由表管理器（JSON 持久化读写）
│   │   └── router.py            # 消息路由器（意图匹配 + round_robin）
│   └── __init__.py
├── registry/
│   ├── __init__.py
│   └── workflows.py             # Spoke 注册表（32 Agent 静态定义）
├── agents/                      # 各 Spoke Agent 适配器
├── config/
│   └── AKO_hub_config.yaml      # 主配置文件
├── data/
│   ├── routing_table.json       # 路由表（自动生成）
│   └── agent_state.json         # Agent 状态
├── logs/
│   └── hub.log
├── tests/
│   ├── test_core.py
│   └── test_hub.py
└── docs/
    ├── AKO_hub_whitepaper_v1.0.md
    ├── AKO统一调度平台白皮书_v0.1.md
    └── ARCHITECTURE_v1.md
```

### 3.2 数据流

```
CLI --sync-registry / --status / dispatch / health-check
    ↓
参数校验 + 配置加载（config_loader.py）
    ↓
RegistryClient.fetch_agents()
    ├── HTTP 远程（registry_endpoint /agents）
    └── 本地 fallback（registry/workflows.py SPOKE_REGISTRY）
    ↓
RoutingTable.sync_from_agents() → data/routing_table.json
    ↓
MessageRouter.route(intent/target)
    ├── importlib 直调（agents.xxx_adapter.run()）
    └── subprocess 子进程（stdin JSON → stdout JSON）
    ↓
结果输出（日志文件 / API 响应）
```

### 3.3 错误处理

| 错误码 | 场景 | 处理方式 | 日志级别 |
|--------|------|----------|----------|
| E001 | 配置文件缺失 | 抛出 FileNotFoundError，退出码 1 | ERROR |
| E002 | 依赖未安装 | 提示安装命令，退出码 2 | ERROR |
| E003 | 输入参数无效 | 打印帮助信息，退出码 3 | WARNING |
| E004 | 注册中心不可达 | 自动回退到本地 registry/workflows.py | WARNING |
| E005 | 路由表为空 | 提示先执行 --sync-registry | ERROR |
| E006 | Agent 不存在 | 列出可用 Agent ID 前 10 个 | ERROR |
| E007 | 模块导入失败 | 提示 Agent 项目可能不在本机 | WARNING |

---

## 四、部署与运行

### 4.1 环境要求

| 资源 | 最低要求 | 推荐配置 |
|------|----------|----------|
| Python | 3.9 | 3.11+ |
| 内存 | 512 MB | 1 GB |
| 磁盘 | 200 MB | 500 MB |
| 网络 | 可访问 registry_endpoint | 蒲公英组网 + 百度云盘同步 |

### 4.2 安装步骤

```bash
pip install -r requirements.txt
python src/core/main.py --help
```

### 4.3 运行方式

```bash
# 同步注册表
python src/core/main.py --config config/AKO_hub_config.yaml --sync-registry

# 查看路由表状态
python src/core/main.py --config config/AKO_hub_config.yaml --status

# 健康检查
python src/core/main.py health-check

# 意图路由
python src/core/main.py --route "结构设计"

# 派发任务（测试模式）
python src/core/main.py dispatch AKO_architect_agent --test

# 调试模式
python src/core/main.py --config config/AKO_hub_config.yaml --log-level DEBUG
```

---

## 五、配置说明

### 5.1 主配置文件

`config/AKO_hub_config.yaml`

```yaml
agent:
  id: "AKO_hub"
  name: "总线调度 Agent"
  log_level: "INFO"

registry:
  agent_id: "AKO_registry_agent"
  endpoint: "http://localhost:PORT"
  sync_interval: 60
  timeout: 10

routing:
  strategy: "round_robin"
  timeout: 30
  retry_count: 3
  retry_backoff: 2

health_check:
  interval: 30
  timeout: 5
  failure_threshold: 3

logging:
  level: "INFO"
  path: "logs/hub.log"
  max_size: "10MB"
  backup_count: 5

storage:
  routing_table: "data/routing_table.json"
  agent_state: "data/agent_state.json"
```

---

## 六、测试与验证

### 6.1 单元测试

```bash
pytest tests/ -v
```

### 6.2 注册表验证

```bash
# 同步后验证 Agent 数量
python src/core/main.py --sync-registry
(Get-Content data/routing_table.json | Select-String '"agent_id"' -AllMatches).Matches.Count
# 期望输出: 32
```

---

## 七、版本历史

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| 2.0.0 | 2026-07-31 | 完善白皮书：补全能力表、架构、依赖；修复 agent_card 注册状态 | AKO_studio |
| 1.0.0 | 2026-07-30 | 初始版本（模板占位） | AKO_studio |

---

## 八、附录

### 8.1 相关 Agent

| Agent | 关系 | 交互方式 |
|-------|------|----------|
| AKO_registry_agent | 上游注册中心 | HTTP /agents 端点拉取 |
| AKO_architect_agent | 下游 Spoke | importlib 直调 |
| AKO_drawing_inspector | 下游 Spoke | importlib 直调 |
| AKO_image_analyzer_agent | 下游 Spoke | importlib 直调 |
| AKO_chat | 下游 Spoke | importlib 直调 |
| AKO_knowledge | 下游 Spoke（知识库服务） | importlib 直调 |
| AKO_reports | 下游 Spoke（报表生成） | subprocess 子进程 |
| AKO_business_agent | 下游 Spoke | importlib 直调 |
| AKO_quote_agent | 下游 Spoke | importlib 直调 |
| AKO_media_agent | 下游 Spoke | importlib 直调 |
| AKO_layout_agent | 下游 Spoke | importlib 直调 |
| AKO_form_extractor | 下游 Spoke | importlib 直调 |
| AKO_netwatch_agent | 下游 Spoke | importlib 直调 |
| AKO_geo | 下游 Workflow | importlib 直调 |
| AKO工作流 | 下游 Workflow | importlib 直调 |
| 其余 16 个业务 Agent | 下游 Spoke | importlib 直调 |

### 8.2 参考文档

- AKO 统一调度平台技术白皮书 v0.2（`docs/AKO统一调度平台白皮书_v0.1.md`）
- AKO Hub-Spoke 架构总览 v2.0（`docs/ARCHITECTURE_v1.md`）
- AKO Agent 全生命周期管理规范

---
> 作者：AKO_studio  
> 日期：2026-07-31  
> 版本：v2.0.0