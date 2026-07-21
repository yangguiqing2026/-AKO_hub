---
ako_doc_id: AKO_README_HUB_001
ako_version: v0.1.0
ako_status: 草稿
ako_title: 调度中枢 (HUB)
ako_category: 平台
ako_author: 杨越浩
ako_created: 2026-07-14
ako_source: AKO_DOC_001 v1.0.0
ako_project_root: D:\AKO_Hub
---

# 调度中枢（HUB）

## 1. 结论前置

AKO_Hub（HUB）是 AKO 智能体体系的统一调度平台，负责 14 个 Agent/Workflow 的元数据管理、任务编排、知识库路由、文件总线和双机同步协调。基于 Hub-Spoke 轻量级架构，以 SQLite 单文件数据库 + LangGraph 状态机为核心，提供 Streamlit Web UI 和命令行双模式操作。当前已稳定运行，支撑 AKO 全部 Agent 的统一调度。

## 2. 修订记录

| 版本 | 日期 | 修订人 | 修订内容 | 签发人 |
|------|------|--------|----------|--------|
| v0.1.0 | 2026-07-14 | 杨越浩 | 按 AKO_DOC_001 初始化 | （待签发） |

## 3. 项目概述

### 3.1 定位

AKO 体系的统一调度中枢，对所有 Agent 和工作流进行集中编排、状态聚合与资源协调。

### 3.2 核心能力

- **元数据管理**：SQLite 存储任务、文件和知识库元数据，支持 CRUD 与多条件检索
- **知识库路由**：统一管理 Chroma 向量库访问，代理所有 Agent 的知识库读写请求
- **文件总线**：统一文件注册、检索和跨项目同步校验
- **分布式锁**：支持双机（办公楼/宿舍楼）环境下的写入控制，防止百度云盘同步冲突
- **任务编排**：基于 LangGraph 的主控状态机（Master Graph），支持意图路由与多级任务分发
- **Web UI 控制面板**：Streamlit + Gradio 双界面，支持任务提交、同步校验、状态监控

### 3.3 技术栈

- Python 3.9+
- LangGraph（编排状态机）
- Streamlit / Gradio（Web UI）
- SQLite（元数据库：`hub_meta.db`、`ako_hub.db`）
- ChromaDB（知识库向量存储）
- FastAPI / uvicorn（API 服务）
- APScheduler（定时任务）
- Ollama + FlagEmbedding（本地嵌入与推理）

## 4. 快速开始

### 4.1 环境要求

- Python 3.9+
- Ollama 运行中（用于本地 LLM / Embedding）
- 8 GB+ 可用内存

### 4.2 安装

```bash
pip install -r requirements.txt
```

初始化（首次使用）：

```bash
# 第一台机器
python scripts/init_hub.py

# 第二台机器
python scripts/init_second_machine.py --machine-id machine_02
```

### 4.3 运行

Web UI（推荐）：

```bash
# Windows
start_web_ui.bat

# Linux/Mac
./start_web_ui.sh
```

浏览器访问 **http://127.0.0.1:7860**。

命令行：

```bash
# 执行任务
python master/runner.py run --intent "结构计算"

# 同步校验
python master/runner.py sync --project taoli

# 查看状态
python master/runner.py status
```

## 5. 项目结构

```
AKO_Hub/
├── start.py                  # 全局启动入口
├── cli.py                    # 命令行界面
├── hub_api.py                # 外部 API 接口
├── hub_server.py             # HTTP API 服务端
├── web_ui.py                 # Gradio Web UI
├── streamlit_app.py          # Streamlit 主应用
├── requirements.txt          # Python 依赖
├── .env / .env.template      # 环境变量配置
├── README.md                 # 本文档
│
├── config/
│   └── hub.yaml              # 主配置文件（同步根、元数据库、Chroma 根等）
│
├── core/                     # 核心模块
│   ├── distributed_lock.py   # 分布式锁（文件锁 + 数据库锁）
│   ├── file_bus.py           # 文件总线（注册、检索、同步校验）
│   ├── hub_db.py             # 元数据库管理（任务、文件、知识库表）
│   └── knowledge_hub.py      # 知识库路由层（Chroma 代理）
│
├── master/                   # 主控编排器
│   ├── graph.py              # LangGraph Master Graph 构建
│   ├── nodes.py              # 状态机节点实现
│   ├── runner.py             # 运行器入口
│   └── state.py              # 状态定义
│
├── registry/
│   └── workflows.py          # 工作流注册表
│
├── router/                   # 意图路由器
│   └── ...                   # 意图分类、任务分发
│
├── console/                  # 控制台管理工具
├── agents/                   # Agent 适配器
├── architect_agent/          # 架构师 Agent 集成
├── ako_geo/                  # 地理内容营销模块
├── heartbeat/                # 心跳监控
│
├── streamlit_pages/          # Streamlit 页面组件
├── database/                 # 数据库迁移与初始化
├── file_bus/                 # 文件总线持久化
├── files/                    # 文件存储目录
│
├── chroma_db/                # Chroma 向量库
├── workflows/                # 工作流定义
│
├── scripts/                  # 初始化与维护脚本
├── tests/                    # 测试文件
├── docs/                     # 设计文档与白皮书
├── logs/                     # 运行日志
└── backups/                  # 数据库备份
```

## 6. 相关文档

| 文档 | 说明 |
|------|------|
| [AKO 统一调度平台白皮书 v0.1](docs/AKO统一调度平台白皮书_v0.1.md) | 总体架构设计与技术方案 |
| [WEB_UI_README.md](WEB_UI_README.md) | Web UI 使用指南 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常见问题排查 |
| [AUDIT_REPORT_KNOWLEDGEHUB_COMPATIBILITY.md](AUDIT_REPORT_KNOWLEDGEHUB_COMPATIBILITY.md) | KnowledgeHub 兼容性审计报告 |
| [WEB_UI_AGENT_SELECTION.md](WEB_UI_AGENT_SELECTION.md) | Agent 选择与调度说明 |

## 7. 术语

| 术语 | 定义 |
|------|------|
| HUB | AKO 统一调度中枢项目代号 |
| Hub-Spoke | 轻量级中心辐射架构：Hub 集中调度，Spoke 各 Agent 独立运行 |
| Master Graph | 基于 LangGraph 构建的主控状态机，负责意图识别与任务编排 |
| 文件总线 (FileBus) | 统一管理所有 Agent 产出的文件注册、检索与同步状态 |
| 知识库路由 (KnowledgeHub) | 代理所有 Chroma 操作，统一 Collection 命名、Embedding 参数 |
| 分布式锁 | 双机环境下通过文件锁 + 数据库锁防止并发写入冲突 |
| 双机同步 | 办公楼与宿舍楼两台电脑通过百度云盘同步数据库，蒲公英组网互通 |
