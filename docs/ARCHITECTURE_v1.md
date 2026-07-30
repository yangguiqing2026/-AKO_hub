# AKO Hub-Spoke 架构总览 v2.1

> 31 Spoke 全量注册完成 + AKO_hub 自注册 + Router 模块交付（2026-07-31）

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
          │             31 Spoke 执行层                               │
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
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │  form    │ │netwatch  │ │  code    │ │ material │    │
          │  │_extractor│ │_agent    │ │_compliance│ │_selector │    │
          │  │  :5003   │ │ 网络监控 │ │ 规范合规 │ │ 材料选型 │    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │ energy   │ │  fire    │ │accessibility│ site    │    │
          │  │_analyzer │ │ _safety  │ │          │ │_planner │    │
          │  │ 能耗分析 │ │ 消防设计 │ │ 无障碍   │ │ 场地规划│    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │   mep    │ │ interior │ │landscape │ │ project  │    │
          │  │_engineer │ │_designer │ │          │ │ _manager │    │
          │  │ 机电设计 │ │ 室内设计 │ │ 景观设计 │ │ 项目管理 │    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
          │  │  cost    │ │   bim    │ │ document │ │  safety  │    │
          │  │_estimator│ │_exporter │ │ _writer  │ │_inspector│    │
          │  │ 造价估算 │ │ BIM导出 │ │ 文档撰写 │ │ 安全巡检 │    │
          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
          │                                                          │
          │  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
          │  │ quality  │ │scheduler │ │ surveyor │                 │
          │  │_inspector│ │          │ │          │                 │
          │  │ 质量检查 │ │ 施工排期 │ │ 测量测绘 │                 │
          │  └──────────┘ └──────────┘ └──────────┘                 │
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
- 所有 API Key 集中在环境配置中
- 所有路径配置在 `config/AKO_hub_config.yaml`
- Spoke 通过 `AKOConfig` 或 Hub .env 加载读取

### 检索：三层降级
1. Hub KnowledgeHub 向量搜索 (credibility: high)
2. DuckDuckGo 网络搜索 (credibility: medium)
3. Mock 数据兜底 (credibility: low)

### 调度：双模式分发
- **importlib 直调**：Hub Web UI 直接 import 适配器模块，低延迟
- **subprocess 子进程**：stdin JSON → stdout JSON，Kahn DAG 拓扑排序，300s 超时，进程级隔离
- 路由：IntentRouter + `routing_rules.yaml`（5 个复合任务 + 18 条关键词）

## 项目清单（全量 32 项：Hub × 1 + Spoke × 31）

| # | 项目 | 目录 | 类型 | 端口 | 调用模式 | 状态 |
|---|------|------|------|------|---------|------|
| 1 | AKO_Hub | E:\AKO_Hub | 中心调度 | 7860 | — | active |
| 2 | AKO_architect_agent | D:\AKO_architect_agent | Agent | — | importlib | registered |
| 3 | AKO_drawing_inspector | D:\AKO_drawing_inspector | Agent | — | importlib | registered |
| 4 | AKO_image_analyzer_agent | E:\AKO_image_analyzer_agent | Agent | 8501 | importlib | registered |
| 5 | AKO_chat | D:\AKO_chat | Agent | 7861 | importlib | registered |
| 6 | AKO工作流 | D:\AKO工作流 | Workflow | 5004 | importlib | registered |
| 7 | AKO_knowledge | D:\AKO_knowledge | 服务 | 8000 | importlib | registered |
| 8 | AKO_geo | E:\AKO_Hub\ako_geo | Workflow | — | importlib | registered |
| 9 | AKO_reports | D:\AKO_Report_Template-v1.0 | Agent | 5001 | subprocess | registered |
| 10 | AKO_business_agent | D:\AKO_business_agent | Agent | 5002 | importlib | registered |
| 11 | AKO_quote_agent | D:\AKO_quote_agent | Agent | 5000 | importlib | registered |
| 12 | AKO_media_agent | D:\AKO_media_agent | Agent | — | importlib | registered |
| 13 | AKO_layout_agent | D:\AKO_layout_agent | Agent | — | importlib | registered |
| 14 | AKO_form_extractor | D:\AKO_form_extractor | Agent | 5003 | importlib | registered |
| 15 | AKO_netwatch_agent | D:\AKO_netwatch_agent | Agent | — | importlib | registered |
| 16 | AKO_code_compliance | D:\AKO_code_compliance | Agent | — | importlib | registered |
| 17 | AKO_material_selector | D:\AKO_material_selector | Agent | — | importlib | registered |
| 18 | AKO_energy_analyzer | D:\AKO_energy_analyzer | Agent | — | importlib | registered |
| 19 | AKO_fire_safety | D:\AKO_fire_safety | Agent | — | importlib | registered |
| 20 | AKO_accessibility | D:\AKO_accessibility | Agent | — | importlib | registered |
| 21 | AKO_site_planner | D:\AKO_site_planner | Agent | — | importlib | registered |
| 22 | AKO_mep_engineer | D:\AKO_mep_engineer | Agent | — | importlib | registered |
| 23 | AKO_interior_designer | D:\AKO_interior_designer | Agent | — | importlib | registered |
| 24 | AKO_landscape | D:\AKO_landscape | Agent | — | importlib | registered |
| 25 | AKO_project_manager | D:\AKO_project_manager | Agent | — | importlib | registered |
| 26 | AKO_cost_estimator | D:\AKO_cost_estimator | Agent | — | importlib | registered |
| 27 | AKO_bim_exporter | D:\AKO_bim_exporter | Agent | — | importlib | registered |
| 28 | AKO_document_writer | D:\AKO_document_writer | Agent | — | importlib | registered |
| 29 | AKO_safety_inspector | D:\AKO_safety_inspector | Agent | — | importlib | registered |
| 30 | AKO_quality_inspector | D:\AKO_quality_inspector | Agent | — | importlib | registered |
| 31 | AKO_scheduler | D:\AKO_scheduler | Agent | — | importlib | registered |
| 32 | AKO_surveyor | D:\AKO_surveyor | Agent | — | importlib | registered |

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
双击 `E:\AKO_Hub\启动AKO.bat`

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
| P8 | 31 Spoke 全量注册 + AKO_hub 自注册 + agent_card/白皮书修复 | ✅ |