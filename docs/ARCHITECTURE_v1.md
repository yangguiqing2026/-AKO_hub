# AKO Hub-Spoke 架构总览 v2.0

> 14 Spoke 全量注册完成 + Router 模块交付（2026-07-14）

## 系统拓扑

```
                    ┌──────────────────────────────────────────────┐
                    │              AKO Hub（中心调度）               │
                    │  ┌────────────┐  ┌──────────┐  ┌──────────┐ │
                    │  │ Streamlit  │  │  Master  │  │IntentRouter│ │
                    │  │  Web UI    │  │  Graph   │  │+ exec     │ │
                    │  │  (:7860)   │  │(LangGraph)│  │(Kahn DAG)│ │
                    │  │ 9节点健康  │  │ 7节点编排│  │5任务/18词│ │
                    │  └─────┬──────┘  └────┬─────┘  └─────┬─────┘ │
                    │        │              │              │       │
                    │        │ importlib 直调│ subprocess   │       │
                    └────────┼──────────────┼──────────────┼───────┘
                             │              │              │
          ┌──────────────────┼──────────────┼──────────────┼──────────┐
          │             14 Spoke 执行层                               │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │architect │ │inspector │ │  image   │ │  工作流   │    │
          │  │_agent    │ │          │ │_analyzer │ │  :5004    │    │
          │  │ 结构设计 │ │ 图纸质检 │ │  :8501   │ │ 全流程编排│    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │  chat    │ │   geo    │ │knowledge │ │ reports  │    │
          │  │  :7861   │ │ 内容营销 │ │  :8000   │ │  :5001    │    │
          │  │ RAG 对话 │ │ ×GEO     │ │ 知识库   │ │ 报表生成  │    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │business  │ │  quote   │ │  media   │ │ layout   │    │
          │  │  :5002   │ │  :5000   │ │ 营销流水 │ │ 智能排版  │    │
          │  │ 商业指挥 │ │ 报价引擎 │ │    线    │ │          │    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐                               │
          │  │  form    │ │netwatch  │                               │
          │  │_extractor│ │_agent    │                               │
          │  │  :5003   │ │ 网络监控 │                               │
          │  └──────────┘ └──────────┘                               │
          └──────────────────────┬───────────────────────────────────┘
                                 │
               ┌─────────────────┼─────────────────┐
               ▼                 ▼                 ▼
      ┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
      │  Knowledge Hub   │ │  File Bus    │ │ Meta Data Center │
      │  ChromaDB +      │ │ 统一注册+检索│ │ age_hub.db       │
      │  bge-m3 (:8000)  │ │              │ │ (SQLite 单文件)  │
      └────────┬─────────┘ └──────┬───────┘ └────────┬─────────┘
               │                  │                  │
               └──────────────────┼──────────────────┘
                                  │
                       ┌──────────┴──────────┐
                       │  Baidu Netdisk Sync │
                       │  + 蒲公英组网        │
                       └─────────────────────┘
```

## 统一化成果

### Embedding 模型：全部 nomic-embed-text → bge-m3 (1024d)
| 项目 | 之前 | 之后 |
|------|------|------|
| AKO_chat | bge-m3 (1024d) | nomic-embed-text（统一化阶段）→ bge-m3（三向量混合检索） |
| drawing_inspector | text-embedding-v2 (1536d) | nomic-embed-text → bge-m3 |
| image_analyzer | 未启用 | nomic-embed-text → bge-m3 |
| architect_agent | — | nomic-embed-text → bge-m3 |

### ChromaDB：统一到 Hub 单一实例
路径: `E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/chroma_db`

Collection 命名规范: `ako_{project_tag}_{kb_type}_{agent_short}`
- `ako_taoli_general_arch` — 通用建筑知识
- `ako_taoli_building_codes_arch` — 建筑规范
- `ako_taoli_photos_insp` — 图像分析
- `ako_taoli_drawings_qc` — 图纸质检

### 配置：Hub .env + hub.yaml 单一来源
- 所有 API Key 集中在 `D:\AKO_Hub\.env`
- 所有路径配置在 `D:\AKO_Hub\config\hub.yaml`
- Spoke 通过 `AKOConfig` 或 Hub .env 加载读取

### 检索：三层降级
1. Hub KnowledgeHub 向量搜索 (credibility: high)
2. DuckDuckGo 网络搜索 (credibility: medium)
3. Mock 数据兜底 (credibility: low)

### 调度：双模式分发
- **importlib 直调**：Hub Web UI 直接 import 适配器模块，低延迟
- **subprocess 子进程**：stdin JSON → stdout JSON，Kahn DAG 拓扑排序，300s 超时，进程级隔离
- 路由：IntentRouter + `routing_rules.yaml`（5 个复合任务 + 18 条关键词）

## 项目清单

| # | 项目 | 目录 | 类型 | 端口 | 调用模式 | 状态 |
|---|------|------|------|------|---------|------|
| 1 | AKO_Hub | D:\AKO_Hub | 中心调度 | 7860 | — | active |
| 2 | AKO_architect_agent | D:\AKO_architect_agent | Agent | — | importlib | registered |
| 3 | AKO_drawing_inspector | D:\AKO_drawing_inspector | Agent | — | importlib | registered |
| 4 | AKO_image_analyzer | D:\AKO_image_analyzer | Agent | 8501 | importlib | registered |
| 5 | AKO_chat | D:\AKO_chat | Agent | 7861 | importlib | registered |
| 6 | AKO工作流 | D:\AKO工作流 | Workflow | 5004 | importlib | registered |
| 7 | AKO_knowledge | D:\AKO_knowledge | 服务 | 8000 | importlib | registered |
| 8 | AKO_geo | D:\AKO_Hub\ako_geo | Workflow | — | importlib | registered |
| 9 | AKO_reports | D:\AKO_Report_Template-v1.0 | Agent | 5001 | subprocess | registered |
| 10 | AKO_business_agent | D:\AKO_business_agent | Agent | 5002 | importlib | registered |
| 11 | AKO_quote_agent | D:\AKO_quote_agent | Agent | 5000 | importlib | registered |
| 12 | AKO_media_agent | D:\AKO_media_agent | Agent | — | importlib | registered |
| 13 | AKO_layout_agent | D:\AKO_layout_agent | Agent | — | importlib | registered |
| 14 | AKO_form_extractor | D:\AKO_form_extractor | Agent | 5003 | importlib | registered |
| 15 | AKO_netwatch_agent | D:\AKO_netwatch_agent | Agent | — | importlib | registered |

## 统一入口

### CLI (`python cli.py`)
```
python cli.py status              # 全局状态
python cli.py hub run --intent    # Hub 任务调度
python cli.py architect "..."     # 结构设计
python cli.py inspector inspect   # 图纸质检
python cli.py image analyze       # 图像分析
python cli.py chat                # 启动 RAG 服务
python cli.py workflow --file     # 执行工作流
python cli.py knowledge           # 启动知识 API
python cli.py ui                  # 启动 Web UI
python cli.py launch              # 一键启动全部
```

### Web UI (Streamlit :7860, 9 节点健康检查)
1. 执行任务 — Master Graph 任务调度
2. 同步校验 — 文件一致性检查
3. 系统状态 — 运行统计
4. 文件列表 — 文件管理
5. 管理 Agent — Spoke 注册管理
6. RAG 对话 — 知识库问答
7. 图像分析 — 上传图像 AI 分析
8. 工作流 — 陶粒墙板全流程

### 一键启动
双击 `D:\AKO_Hub\启动AKO.bat`

## 阶段完成记录

| 阶段 | 内容 | 状态 |
|------|------|------|
| P1 | Hub 路由修复 + registry + sync_monitor + chat适配器 | ✅ |
| P2 | 统一 embedding + 知识迁移 + drawing_inspector Hub模式 | ✅ |
| P3 | ako_config 统一包 + .env 合并 + 各项目配置对齐 + 双写 | ✅ |
| P4 | 工作流适配器 + retriever 三层降级 + registry 更新 | ✅ |
| P5 | 统一 CLI + Gradio 整合(3新标签) + 一键启动脚本 | ✅ |
| P6 | Streamlit 迁移(Gradio→Streamlit) + 9 节点健康检查 + 14 Spoke 全量注册 | ✅ |
| P7 | Router 模块(IntentRouter + task_executor Kahn DAG + routing_rules.yaml) + 双调度模式 | ✅ |
