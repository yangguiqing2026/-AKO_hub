---
title: AKO_Hub白皮书_v2.0.0
description: 总线调度中枢Agent白皮书
author: AKO_studio
date: 2026-08-14
version: v2.0.0
tags: [AKO, documentation, whitepaper]
---

# AKO_Hub 白皮书

> **Agent ID**：AKO_hub
> **版本**：v2.0.0
> **作者**：AKO_studio
> **状态**：active
> **等级**：S
> **庭**：PROD
> **日期**：2026-08-14

---

## 一、Agent概述

### 1.1 定位

> AKO Hub 是 AKO 体系的总线调度中枢，作为所有 Agent 的注册中心、意图路由器和工作流编排引擎，驱动整个 AKO 社会的高效运转。

### 1.2 核心职责

- **Agent 注册与发现**：统一管理所有 AKO Agent 的注册信息，提供服务发现能力
- **意图路由**：基于 18 个关键词 + 5 种复合任务模式，精准路由用户请求到对应 Agent
- **工作流编排**：使用 LangGraph Master Graph 实现复杂多步骤工作流编排
- **健康巡检**：7×24 小时监控 31 个 Spoke Agent 的心跳状态，异常实时告警
- **双模式调度**：支持 importlib 直调（进程内）和 subprocess 子进程两种调度模式

### 1.3 依赖关系

- 上游依赖：AKO_law_agent（合规咨询）、AKO_standard_agent（标准查询）
- 下游服务：所有 Spoke Agent（31个）
- 外部依赖：Python >= 3.9、LangGraph >= 0.0.40、FastAPI >= 0.100.0、pyyaml

---

## 二、功能规格

### 2.1 核心命令

| 命令名 | 说明 | 参数 |
|--------|------|------|
| `cmd_register` | 注册新Agent | agent_card.yaml |
| `cmd_route` | 意图路由 | user_intent_text |
| `cmd_workflow` | 编排工作流 | workflow_def |
| `cmd_heartbeat` | 心跳上报 | agent_id, status |
| `cmd_health_report` | 健康报告 | target_agent（可选） |

### 2.2 功能列表

- **意图识别引擎**：支持 18 个基础关键词（建筑/审计/图表/排版等）和 5 种复合任务模式
- **Agent注册表**：维护所有Agent的元数据、能力描述、接口地址
- **LangGraph Master Graph**：多Agent协作工作流的编排引擎，支持条件分支与并行执行
- **心跳监控系统**：实时监控 31 个 Spoke Agent 的运行状态，支持故障自愈
- **双模式调度**：
  - importlib 直调：进程内调用，延迟低，适合轻量任务
  - subprocess 子进程：进程隔离，适合重型或不稳定 Agent
- **WebUI 界面**：Streamlit 驱动的可视化仪表盘（端口 7860）
- **事件总线**：发布/订阅模式，支持 Agent 间事件通知

---

## 三、API接口

### 3.1 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康探针 |
| `/register` | POST | 注册Agent |
| `/route` | POST | 意图路由 |
| `/workflow` | POST | 工作流编排 |
| `/heartbeat` | POST | 心跳上报 |
| `/agents` | GET | 查询Agent列表 |
| `/health_report` | GET | 健康状态报告 |

---

## 四、配置说明

### 4.1 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `PORT` | Hub监听端口，默认7860（WebUI） | ✅ |
| `AGENT_REGISTRY_PATH` | Agent注册表路径 | ✅ |
| `HEARTBEAT_INTERVAL` | 心跳检测间隔（秒） | ✅ |
| `SCHEDULER_MODE` | 调度模式（importlib/subprocess） | ✅ |
| `SPOKE_COUNT` | 监控的Spoke Agent数量 | ✅ |
| `LANGGRAPH_CHECKPOINT_DIR` | LangGraph检查点目录 | ❌ |

---

## 五、安全与合规

> - 凭证管理：全部通过 `.env` 文件管理，零硬编码
> - 标签规范：遵守AKO_标签宪法_v1.0.0，仅用48叶子标签
> - 铁律合规：遵守AKO_铁律_v1.0.0
> - 调度安全：subprocess 调度模式下对子进程进行资源隔离和超时控制

---

## 六、版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0.0 | 2026-07-30 | 初始版本，支持Agent注册、意图路由与基础调度 |
| v2.0.0 | 2026-08-14 | 新增LangGraph Master Graph工作流编排，升级为S级中枢，监控31个Spoke Agent |

---

*作者：AKO_studio*
