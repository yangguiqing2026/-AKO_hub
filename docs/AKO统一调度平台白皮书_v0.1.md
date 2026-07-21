# AKO 统一调度平台技术白皮书

**文档编号：** AGE-TECH-AKO-HUB-001  
**版本：** v0.2  
**编制日期：** 2026-07-14  
**编制人：** 技术架构组  
**适用范围：** AKO 智能体体系  
**密级：** 内部技术资料

---

## 1. 项目背景与现状基线

### 1.1 现状资产清单

| 序号 | 资产类别 | 名称 | 技术形态 | 部署位置 | 调用模式 | 状态 |
|:---:|---------|------|---------|---------|---------|:---|
| A-01 | Agent | AKO_architect_agent | 独立推理体 | 本地 Ollama | importlib | 已运行 |
| A-02 | Agent | AKO_drawing_inspector | 独立推理体 | 本地 Python | importlib | 已运行 |
| A-03 | Agent | AKO_image_analyzer | LangGraph 状态机 | 本地 Python (:8501) | importlib | 已运行 |
| A-04 | Workflow | AKO工作流 | LangGraph 状态机 | 本地 Python (:5004) | importlib | 已运行 |
| A-05 | Agent | AKO_chat | FastAPI RAG | 本地 Python (:7861) | importlib | 已运行 |
| A-06 | Workflow | AKO_geo | 内容营销×GEO | 本地 Python | importlib | 已运行 |
| A-07 | Agent | AKO_knowledge | ChromaDB + FastAPI | 百度云盘同步目录 (:8000) | importlib | 已运行 |
| A-08 | Agent | AKO_reports | Jinja2 报表渲染 | 本地 Python (:5001) | subprocess | 已运行 |
| A-09 | Agent | AKO_business_agent | 商业作战指挥 | 本地 Python (:5002) | importlib | 已运行 |
| A-10 | Agent | AKO_quote_agent | 装配式报价引擎 | 本地 Python (:5000) | importlib | 已运行 |
| A-11 | Agent | AKO_media_agent | 内容营销流水线 | 本地 Python | importlib | 已运行 |
| A-12 | Agent | AKO_layout_agent | 智能排版 | 本地 Python | importlib | 已运行 |
| A-13 | Agent | AKO_form_extractor | 表单数据提取 | 本地 Python (:5003) | importlib | 已运行 |
| A-14 | Agent | AKO_netwatch_agent | 网络监控 | 本地 Python | importlib | 已运行 |
| I-01 | 基础设施 | 蒲公英组网 | 点对点 VPN | 双机互通 | — | 已运行 |
| I-02 | 基础设施 | 百度云盘 | 文件级同步 | 双机共享 | — | 已运行 |
| I-03 | 基础设施 | AKO Hub（调度中心） | Streamlit + LangGraph | 本地 Python (:7860) | — | 已运行 |

### 1.2 核心痛点（P0 级）

1. **知识库孤岛**：各 Agent 若自行访问 Chroma，Collection 命名混乱，embedding 模型参数不一致，检索结果不可复用。
2. **文件产出离散**：Agent 与工作流生成的文件散落在各自工作目录，无统一注册机制，跨项目检索困难。
3. **任务无编排**：无总控节点，Workflow 之间无法级联触发，人工介入节点多。
4. **双机状态不一致**：两台电脑通过百度云盘同步数据库文件，但文件是否已同步、版本是否一致，无校验机制。

### 1.3 设计目标

- **目标一（P0）**：建立统一元数据中心，实现知识库与文件产出的集中注册与检索。
- **目标二（P1）**：建立主控编排器（Master Graph），实现 Agent 与 Workflow 的任务分发与状态聚合。
- **目标三（P2）**：建立双机同步状态监控，实现文件一致性自动校验。

---

## 2. 总体架构设计

### 2.1 架构选型：Hub-Spoke 轻量级模式

基于以下约束条件：
- 无 CUDA，安全内存约 8–9 GB；
- 网络受限，不可依赖云端 MLOps 平台；
- 双机通过蒲公英 + 百度云盘同步；
- 工作流已基于 LangGraph 构建。

**结论：不引入 Kubernetes、不引入云端向量库、不引入额外数据库服务。** 统一调度层基于 SQLite 单文件 + Python 类封装实现，零配置、零守护进程、可同步。

### 2.2 架构拓扑图

```
┌─────────────────────────────────────────────────────────────┐
│                      AKO Hub（主控编排器）                    │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Streamlit   │  │ Master      │  │ IntentRouter        │  │
│  │ Web UI      │  │ Graph       │  │ + task_executor     │  │
│  │ (:7860)     │  │ (LangGraph) │  │ (Kahn DAG 拓扑)     │  │
│  │ 9节点健康检查│  │ 7节点编排   │  │ 5复合任务/18关键词  │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         │  importlib 直调 │   subprocess 子进程 │             │
│         └────────────────┼─────────────────────┘             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                    14 Spoke 执行层                           │
│                                                             │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐          │
│  │architect ││inspector ││  image   ││  工作流   │          │
│  │_agent    ││          ││_analyzer ││  :5004    │          │
│  │ 结构设计 ││ 图纸质检 ││  :8501   ││ 全流程编排│          │
│  └──────────┘└──────────┘└──────────┘└──────────┘          │
│                                                             │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐          │
│  │  chat    ││   geo    ││knowledge ││ reports  │          │
│  │  :7861   ││ 内容营销 ││  :8000   ││  :5001    │          │
│  │ RAG 对话 ││ ×GEO     ││ 知识库   ││ 报表生成  │          │
│  └──────────┘└──────────┘└──────────┘└──────────┘          │
│                                                             │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐          │
│  │business  ││ quote    ││  media   ││ layout   │          │
│  │  :5002   ││  :5000   ││ 营销流水 ││ 智能排版  │          │
│  │ 商业指挥 ││ 报价引擎 ││    线    ││          │          │
│  └──────────┘└──────────┘└──────────┘└──────────┘          │
│                                                             │
│  ┌──────────┐┌──────────┐                                   │
│  │  form    ││netwatch  │                                   │
│  │_extractor││_agent    │                                   │
│  │  :5003   ││ 网络监控 │                                   │
│  └──────────┘└──────────┘                                   │
└──────────────────────────┬──────────────────────────────────┘
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

### 2.3 数据流定义

1. **下行流（Master → Spoke）**：任务分发时，Master Graph 通过 `payload` 下发输入参数 + 挂载的知识库 ID 列表 + 输出目录约束。
2. **上行流（Spoke → Master）**：Spoke 完成任务后，返回输出文件路径列表，由 `file_collector` 统一注册到 `file_registry` 表。
3. **旁路流（Spoke ↔ Knowledge Hub）**：Spoke 在运行过程中通过 `KnowledgeHub` 接口读写向量库，但 Collection 的创建与销毁必须经 `kb_allocator` 审批注册。
4. **调度双路径**：Hub 通过两种模式调用 Spoke——`importlib` 直调（Hub Web UI 直接 import 适配器模块，低延迟）和 `subprocess` 子进程（stdin JSON → stdout JSON，Kahn DAG 拓扑排序，300s 超时，进程级隔离）。IntentRouter 根据 `routing_rules.yaml`（5 个复合任务 + 18 条关键词路由）自动选择调度路径。

---

## 3. 元数据中心设计（Meta Data Center）

### 3.1 技术选型：SQLite 单文件

**理由：**
- 零配置：无需安装服务，Python 标准库支持；
- 单文件同步：直接放入百度云盘同步目录，双机自动同步；
- 资源占用：空库约 50 KB，10 万条记录约 20 MB，对 8–9 GB 内存无压力；
- 事务支持：ACID 保证元数据一致性。

**约束：** 禁止在 SQLite 中存储大文件二进制内容，仅存储文件路径与元数据。

### 3.2 数据库 Schema

#### 3.2.1 知识库注册表（knowledge_base）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| kb_id | TEXT | PRIMARY KEY | 知识库唯一标识，如 `ako_tech_doc` |
| kb_name | TEXT | NOT NULL | 可读名称，如 "技术方案文档库" |
| agent_name | TEXT | NOT NULL | 归属 Agent，如 `AKO_architect_agent` |
| collection_name | TEXT | NOT NULL | Chroma 中实际 Collection 名 |
| embedding_model | TEXT | DEFAULT 'nomic-embed-text' | 嵌入模型，全局统一 |
| vector_db_path | TEXT | NOT NULL | Chroma 持久化目录绝对路径 |
| description | TEXT | | 用途说明 |
| created_at | TEXT | NOT NULL | ISO 8601 时间戳 |
| updated_at | TEXT | NOT NULL | ISO 8601 时间戳 |

**Collection 命名规范（强制）：**
```
ako_{project_tag}_{kb_type}_{agent_name_short}

示例：
  ako_tech_struct_arch      → 陶粒墙板结构计算，architect 用
  ako_drawing_qc_ins        → 图纸质检，inspector 用
  ako_common_material       → 通用材料库，跨 Agent 共享
```

#### 3.2.2 文件产出注册表（file_registry）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| file_id | TEXT | PRIMARY KEY | 全局唯一，由系统生成 |
| source_agent | TEXT | NOT NULL | 生成者 |
| source_node | TEXT | | LangGraph 具体节点名 |
| rel_path | TEXT | NOT NULL | 相对于同步根目录的相对路径 |
| abs_path | TEXT | NOT NULL | 绝对路径（冗余，便于校验） |
| file_type | TEXT | NOT NULL | pdf / docx / xlsx / md / png / jpg / json |
| project_tag | TEXT | NOT NULL | 项目标签：如 `taoli`, `sample`, `common` |
| version_tag | TEXT | DEFAULT 'v0.1' | 版本号 |
| file_hash | TEXT | | SHA-256，用于同步校验 |
| file_size | INTEGER | | 字节数 |
| created_at | TEXT | NOT NULL | ISO 8601 时间戳 |
| is_synced | INTEGER | DEFAULT 0 | 0=未校验 1=已同步 2=冲突 |
| sync_verified_at | TEXT | | 上次校验时间 |

#### 3.2.3 任务流水表（task_queue）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| task_id | TEXT | PRIMARY KEY | 全局唯一，如 `T-20260615-001` |
| workflow_id | TEXT | NOT NULL | 调用的 workflow 标识 |
| trigger_agent | TEXT | | 触发者（可为人工 `manual`） |
| trigger_type | TEXT | DEFAULT 'manual' | manual / auto / cron |
| payload | TEXT | | JSON 序列化输入参数 |
| status | TEXT | NOT NULL | pending / running / done / failed / cancelled |
| output_file_ids | TEXT | | JSON 数组，关联 file_registry |
| error_log | TEXT | | 失败原因 |
| started_at | TEXT | | ISO 8601 |
| finished_at | TEXT | | ISO 8601 |

### 3.3 建表 SQL

```sql
-- knowledge_base
CREATE TABLE IF NOT EXISTS knowledge_base (
    kb_id TEXT PRIMARY KEY,
    kb_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    collection_name TEXT NOT NULL UNIQUE,
    embedding_model TEXT DEFAULT 'nomic-embed-text',
    vector_db_path TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- file_registry
CREATE TABLE IF NOT EXISTS file_registry (
    file_id TEXT PRIMARY KEY,
    source_agent TEXT NOT NULL,
    source_node TEXT,
    rel_path TEXT NOT NULL,
    abs_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    project_tag TEXT NOT NULL,
    version_tag TEXT DEFAULT 'v0.1',
    file_hash TEXT,
    file_size INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    is_synced INTEGER DEFAULT 0,
    sync_verified_at TEXT
);

-- task_queue
CREATE TABLE IF NOT EXISTS task_queue (
    task_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    trigger_agent TEXT,
    trigger_type TEXT DEFAULT 'manual',
    payload TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed','cancelled')),
    output_file_ids TEXT,
    error_log TEXT,
    started_at TEXT,
    finished_at TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_file_project ON file_registry(project_tag);
CREATE INDEX IF NOT EXISTS idx_file_agent ON file_registry(source_agent);
CREATE INDEX IF NOT EXISTS idx_file_type ON file_registry(file_type);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_kb_agent ON knowledge_base(agent_name);
```

---

## 4. 知识库统一路由层（Knowledge Hub）

### 4.1 设计原则

- **封装原则**：所有 Spoke 不直接实例化 `chromadb.Client`，必须通过 `KnowledgeHub` 接口。
- **命名管控原则**：Collection 名称由 `KnowledgeHub` 根据注册表统一生成，禁止 Spoke 自定义。
- **模型锁定原则**：全局 embedding_model 锁定为 `nomic-embed-text`，如需变更需经 Master Graph 审批并重建全库。

### 4.2 接口定义

```python
class KnowledgeHub:
    # 初始化时绑定 SQLite + Chroma 持久路径
    def __init__(self, db_path: str, chroma_root: str) -> None
    
    # 注册知识库（Master 调用）
    def register_kb(self, kb_id: str, kb_name: str, agent_name: str,
                    project_tag: str, kb_type: str,
                    vector_db_path: str = None) -> str
    # 返回 collection_name
    
    # 获取 Collection（Spoke 调用）
    def get_collection(self, kb_id: str) -> chromadb.Collection
    
    # 统一检索（Spoke 调用）
    def query(self, kb_id: str, query_text: str, n_results: int = 5,
              where: dict = None) -> dict
    
    # 统一写入（Spoke 调用）
    def upsert(self, kb_id: str, ids: list, documents: list,
               metadatas: list = None, embeddings: list = None) -> None
    
    # 列出某 Agent 的所有知识库
    def list_kb_by_agent(self, agent_name: str) -> list[dict]
    
    # 列出某项目的所有知识库
    def list_kb_by_project(self, project_tag: str) -> list[dict]
```

### 4.3 现有知识库注册计划

| kb_id | kb_name | agent_name | collection_name | 现状 |
|-------|---------|-----------|-----------------|------|
| ako_knowledge_base | AKO 通用知识库 | ALL | ako_common_base | 已存在，需注册 |
| ako_tech_struct | 结构计算文档库 | AKO_architect_agent | ako_tech_struct_arch | 待创建 |
| ako_drawing_qc | 图纸质检库 | AKO_drawing_inspector | ako_drawing_qc_ins | 待创建 |
| ako_image_corpus | 图像分析语料库 | AKO_image_analyzer | ako_image_corpus_ana | 待创建 |

---

## 5. 文件总线设计（File Bus）

### 5.1 目录命名规范（强制）

```
AKO_Hub/                               # 同步根目录
├── age_hub.db                         # 元数据库
├── chroma_db/                         # Chroma 向量库（已是现有）
├── files/                             # 所有产出文件
│   ├── common/                        # 跨项目共享
│   ├── taoli_wallboard/               # 陶粒墙板项目
│   │   ├── tech_docs/                 # 技术文档
│   │   ├── drawings/                # 图纸
│   │   ├── reports/                   # 报告
│   │   └── bp/                      # 商业计划书
│   ├── sample_house/                  # 样板房项目
│   │   ├── vibe_design/               # 氛围设计
│   │   ├── acceptance/               # 验收小样
│   │   └── audit/                    # 传播审计
│   └── system/                        # 系统日志与备份
│       ├── logs/                      # 运行日志
│       └── backups/                   # 数据库备份
└── docs/                              # 平台文档
    └── whitepapers/                   # 白皮书
```

### 5.2 文件命名规范（强制）

```
{version_tag}_{YYYYMMDD}_{HHMMSS}_{source_agent}_{descriptive_name}.{ext}

示例：
  v0.1_20260615_143052_ako_architect_结构计算书.md
  v0.2_20260620_091500_ako_inspector_图纸质检报告.xlsx
```

### 5.3 接口定义

```python
class FileBus:
    def __init__(self, db_path: str, root_dir: str) -> None
    
    # 注册文件（Spoke 完成后必须调用）
    def register(self, source_agent: str, source_node: str,
                 rel_path: str, file_type: str, project_tag: str,
                 version_tag: str = "v0.1") -> str
    # 返回 file_id
    
    # 计算文件哈希
    def compute_hash(self, abs_path: str) -> str
    
    # 按项目检索
    def find_by_project(self, project_tag: str,
                        file_type: str = None) -> list[dict]
    
    # 按 Agent 检索
    def find_by_agent(self, agent_name: str) -> list[dict]
    
    # 同步校验（比对 file_hash 与 file_size）
    def verify_sync(self, file_id: str) -> dict
    # 返回 {file_id, is_synced, local_hash, remote_hash, status}
    
    # 生成目录（如不存在）
    def ensure_dir(self, rel_path: str) -> str
```

---

## 6. 主控编排器设计（Master Graph）

### 6.1 状态定义（MasterState）

```python
class MasterState(TypedDict):
    task_id: str                          # 任务唯一标识
    target_workflow: str                  # 目标工作流 ID
    target_agent: str                     # 目标 Agent（如 workflow 内嵌 agent）
    input_payload: dict                   # 输入参数
    required_kb_ids: list[str]            # 需挂载的知识库
    output_dir: str                       # 输出目录约束
    generated_files: list[str]            # 产出 file_id 列表
    status: str                           # pending / running / done / failed
    error_log: str                        # 错误信息
    started_at: str                       # ISO 8601
    finished_at: str                      # ISO 8601
```

### 6.2 节点定义

| 节点名 | 职责 | 输入 | 输出 |
|-------|------|------|------|
| task_router | 解析输入，确定 target_workflow | MasterState | MasterState（含 target_workflow） |
| kb_allocator | 校验知识库是否存在，权限是否匹配 | MasterState（含 required_kb_ids） | MasterState（含 kb_status） |
| workflow_caller | 调用 Spoke 工作流 | MasterState + payload | MasterState（含 output_file_paths） |
| file_collector | 将 Spoke 产出注册到 file_registry | 文件路径列表 | MasterState（含 generated_files） |
| sync_monitor | 校验文件同步状态 | file_id 列表 | 同步状态报告 |
| error_handler | 失败重试或终止 | 异常信息 | MasterState（status=failed） |
| state_aggregator | 聚合多任务状态 | 子任务列表 | 全局状态视图 |

### 6.3 工作流注册表（Spoke Registry）

| workflow_id | 名称 | 类型 | 挂载知识库 | 输出目录 | 调用模式 | 状态 |
|-------------|------|------|-----------|---------|---------|------|
| AKO_architect_agent | 建筑结构设计 | Agent | ako_knowledge_base, ako_tech_struct | taoli_wallboard/tech_docs | importlib | 已注册 |
| AKO_drawing_inspector | 图纸质检 | Agent | ako_knowledge_base, ako_drawing_qc | taoli_wallboard/drawings/qc | importlib | 已注册 |
| AKO_image_analyzer | 图像分析 | Agent | ako_knowledge_base, ako_image_corpus | taoli_wallboard/reports/analyzer | importlib | 已注册 |
| AKO工作流 | 陶粒墙板全流程编排 | Workflow | ako_taoli_general_arch, ako_taoli_building_codes_arch | taoli_wallboard/workflow_outputs | importlib | 已注册 |
| AKO_chat | RAG 知识库对话 | Agent | ako_taoli_general_arch | taoli_wallboard/chat_logs | importlib | 已注册 |
| AKO_geo | 内容营销×GEO | Workflow | hub_geo_anchors, ako_taoli_general_arch | geo_output | importlib | 已注册 |
| AKO_knowledge | 知识库服务 | Agent | — | knowledge_output | importlib | 已注册 |
| AKO_reports | 报表模版生成 | Agent | — | reports_output | subprocess | 已注册 |
| AKO_business_agent | 商业作战指挥 | Agent | — | business_output | importlib | 已注册 |
| AKO_quote_agent | 装配式报价引擎 | Agent | — | quote_output | importlib | 已注册 |
| AKO_media_agent | 内容营销流水线 | Agent | — | media_output | importlib | 已注册 |
| AKO_layout_agent | 智能排版 | Agent | — | layout_output | importlib | 已注册 |
| AKO_form_extractor | 表单数据提取 | Agent | — | form_extractor_output | importlib | 已注册 |
| AKO_netwatch_agent | 网络监控 | Agent | — | netwatch_output | importlib | 已注册 |

---

## 7. 实施路径（P0 → P1 → P2）

### 7.1 P0：元数据与总线基座（1–2 天）

**目标**：让现有 Agent 与 Workflow 的产出可被统一检索。

**任务清单：**
1. [ ] 在百度云盘同步目录创建 `AKO_Hub/` 目录结构。
2. [ ] 初始化 `age_hub.db`，执行建表 SQL。
3. [ ] 实现 `KnowledgeHub` 类，封装 Chroma 访问。
4. [ ] 实现 `FileBus` 类，封装文件注册与检索。
5. [ ] 将现有 `AKO_knowledge` Collection 注册到 `knowledge_base` 表。
6. [ ] 修改 `AKO_architect_agent`、`AKO_drawing_inspector`、`AKO_image_analyzer` 的入口，使其在生成文件后调用 `FileBus.register()`。

**交付物：**
- `age_hub.db`（已初始化）
- `core/knowledge_hub.py`
- `core/file_bus.py`
- `scripts/init_hub.py`（一键初始化脚本）

### 7.2 P1：Master Graph 编排（3–5 天）

**目标**：实现 Workflow 之间的自动触发与状态聚合。

**任务清单：**
1. [ ] 定义 `MasterState` 数据结构。
2. [ ] 用 LangGraph 构建 Master Graph，含 `task_router`、`kb_allocator`、`workflow_caller`、`file_collector` 节点。
3. [ ] 实现 `workflow_caller` 对 `AKO_image_analyzer` 的调用接口（通过 `Runnable` 或 `subprocess`）。
4. [ ] 将 `AKO_architect_agent` 和 `AKO_drawing_inspector` 包装为 LangGraph 子图（如果尚未是）。
5. [ ] 在 `task_queue` 表中实现任务持久化，支持中断恢复。

**交付物：**
- `master/graph.py`（Master Graph 构建）
- `master/state.py`（状态定义）
- `registry/workflows.py`（工作流注册表）
- `tests/test_master_graph.py`（端到端测试）

### 7.3 P2：同步监控与扩展（后续）

**目标**：双机一致性校验 + 新 Workflow 即插即用。

**任务清单：**
1. [ ] 实现 `sync_monitor` 节点，比对文件 SHA-256 与大小。
2. [ ] 在 `age_hub.db` 中增加 `sync_log` 表，记录每次校验结果。
3. [ ] 为 `cherry_studio` 或 `kimi_desktop` 提供 CLI/MCP 调用接口，支持从桌面端直接下发任务。
4. [ ] 预留 `youtu-agent` 或其他第三方工作流的注册位。

---

## 8. 安全与约束

### 8.1 写入约束

- `KnowledgeHub` 的 `register_kb()` 仅可由 Master Graph 或管理员脚本调用，Spoke 无权自行创建 Collection。
- `FileBus` 的 `register()` 为强制调用，Spoke 不注册的文件不进入全局检索。
- `task_queue` 中 `status` 字段状态机：`pending → running → (done | failed)`，禁止直接跳变。

### 8.2 备份策略

- `age_hub.db` 在每次 Master Graph 完成一次完整任务流后自动复制到 `AKO_Hub/system/backups/age_hub_{YYYYMMDD}_{HHMMSS}.db`。
- 保留最近 30 份备份，超期自动删除。

### 8.3 双机约束

- 同一时刻仅一台机器执行 Master Graph 写入操作，另一台为只读 standby。通过 `task_queue` 中 `status=running` 的行作为分布式锁（轻量级，非严格分布式锁，但适用于双机场景）。

---

## 9. 附录

### 9.1 术语表

| 术语 | 说明 |
|------|------|
| Hub | 统一调度中心，含元数据、知识库路由、文件总线 |
| Spoke | 被调度的 Agent 或 Workflow |
| Master Graph | LangGraph 构建的主控状态机 |
| Collection | Chroma 向量库中的数据集合 |
| KB | Knowledge Base，知识库 |
| File Bus | 文件总线，统一注册与检索机制 |

### 9.2 版本记录

| 版本 | 日期 | 修订内容 | 修订人 |
|------|------|---------|--------|
| v0.1 | 2026-06-15 | 初稿，P0–P2 架构定义 | 技术架构组 |
| v0.2 | 2026-07-14 | 14 Spoke 全量注册、双调度模式、Streamlit UI、§1.1/§2.2/§2.3/§6.3 同步更新 | 技术架构组 |

---

**文档结束**
