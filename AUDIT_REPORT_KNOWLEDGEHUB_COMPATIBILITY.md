# AKO_Hub Agent 检索逻辑与三向量升级兼容性审查报告

**审查日期**: 2026-06-30  
**审查范围**: `core/knowledge_hub.py` + 7 个 Agent 适配器 + Web UI + Master Graph 节点 + 外部子项目检索路径 + `scripts/reembed_all.py`  
**核心问题**: AKO_Hub 声称升级 bge-m3 三向量 Hybrid Retrieval，各 Agent 检索调用是否兼容？

---

## 1. 执行摘要

| 维度 | 状态 | 说明 |
|------|------|------|
| **三向量数据写入** | ✅ 已实现 | `scripts/reembed_all.py` 通过 FlagEmbedding/Ollama 编码 bge-m3，写入 ChromaDB metadata 中的 `sparse_lexicon` / `colbert_tokens` |
| **三向量检索查询** | ❌ 未实现 | `core/knowledge_hub.py` 的 `query()` 仍是 ChromaDB 原生单向量 `collection.query()` 薄封装，**完全不读取** metadata 中的 sparse/colbert 字段，**无 RRF 融合和 ColBERT 精排** |
| **Hub 层检索调用点** | 🔴 仅 1 个 | `AKO_drawing_inspector/core/rag_engine.py` 的 `CodeRAG._hub_search()` 是唯一经过 `KnowledgeHub.query()` 的检索调用 |
| **外部独立 RAG 栈** | 🔴 4 个 | `AKO_chat`、`AKO工作流`、`AKO_architect_agent`、`AKO_image_analyzer` 均有自己的检索实现，完全绕过 KnowledgeHub |
| **配置层** | 🟡 未统一 | `config/hub.yaml`: `embedding_model: "nomic-embed-text"`；`AKO_drawing_inspector/config/settings.yaml`: `embedding_model: "nomic-embed-text"`，均未改为 bge-m3 |
| **Prompt 层** | 🟢 无硬编码 | Prompt 模板 `{rag_retrieved_codes}` 占位符与检索方式解耦 |

---

## 2. 三向量升级现状深度分析

### 2.1 数据层：脚本已写入三向量到 Metadata

`scripts/reembed_all.py` (691 行) 是完整的三向量重建脚本，支持：

```
bge-m3 Dense (1024-dim)   → ChromaDB native embedding 字段
bge-m3 Sparse Lexicon     → metadata["sparse_lexicon"] (JSON: {bpe_token_id: weight})
bge-m3 ColBERT Tokens     → metadata["colbert_tokens"] (JSON: [[float]*1024, ...] multi-vector)
```

**编码后端支持**:
| 后端 | Dense | Sparse | ColBERT |
|------|-------|--------|---------|
| FlagEmbedding | ✅ | ✅ | ✅ |
| Ollama | ✅ | ✅ (build_hybrid_metadata 近似) | ✅ (build_hybrid_metadata 近似) |

**已运行**：从 `backups/` 目录可见多次 `reembed_20260629_*` 运行记录，表明 reembed 已执行多轮。

### 2.2 查询层：KnowledgeHub.query() 完全不使用三向量

```python
# core/knowledge_hub.py L151-164 (当前代码)
def query(self, kb_id: str, query_text: str, n_results: int = 5, ...) -> Dict[str, Any]:
    col = self.get_collection(kb_id)
    return col.query(
        query_texts=[query_text],
        n_results=n_results,
        where=where,
        where_document=where_document,
    )
```

**问题清单**:

| 缺失项 | 严重度 | 说明 |
|--------|--------|------|
| 无 Sparse Lexicon 查询 | 🔴 P0 | 未生成查询文本的稀疏词权重，未与 ChromaDB 中 `metadata.sparse_lexicon` 做精确匹配打分 |
| 无 ColBERT 精排 | 🔴 P0 | 未加载候选文档的 `metadata.colbert_tokens`，未做 Token-Level 延迟交互计算 |
| 无 RRF 融合 | 🔴 P0 | 缺少 Dense + Sparse + ColBERT 三路分数归一化与 RRF/加权融合 |
| 签名无 `retrieval_mode` | 🟡 P1 | 无法让调用方选择 "hybrid" vs "dense_only" vs "sparse_only" |
| 签名无 `hybrid_weights` | 🟡 P1 | 无法让调用方配置三路权重 |
| 返回值无 `final_scores` | 🟡 P1 | 仅返回 ChromaDB 原生 `distances` 字段，无融合后分数 |
| `embedding_model` 硬编码 | 🟡 P1 | `__init__` 默认 `"nomic-embed-text"`，未对应 bge-m3 |

### 2.3 配置层未更新

**config/hub.yaml**:
```yaml
embedding_model: "nomic-embed-text"  # ❌ 应为 "bge-m3"
```
缺失字段：`retrieval_mode`、`hybrid_weights`、`colbert_rerank_top_k`、`sparse_model`。

**AKO_drawing_inspector/config/settings.yaml**:
```yaml
rag:
  embedding_model: "nomic-embed-text"  # ❌ 应为 "bge-m3"
```

---

## 3. 检索调用链路全景分析

### 3.1 完整调用拓扑

```
                    ┌─────────────────────────────────────────┐
                    │          web_ui.py (Gradio)             │
                    │  ┌──────────┐ ┌────────┐ ┌──────────┐  │
                    │  │RAG 对话   │ │图像分析 │ │ AKO工作流 │  │
                    │  │rag_chat()│ │analyze │ │run_work  │  │
                    │  └────┬─────┘ └───┬────┘ └────┬─────┘  │
                    └───────┼──────────┼───────────┼─────────┘
                            │          │           │
                            ▼          ▼           ▼
              ┌─────────────┐ ┌───────┐ ┌──────────────────┐
              │ AKO_chat    │ │Image  │ │ AKO工作流         │
              │ adapter.run │ │Adapt  │ │ adapter.run       │
              │   ↓         │ │  ↓    │ │   ↓               │
              │ RAGService  │ │subproc│ │ LangGraph.invoke  │
              │  (D:\AKO_   │ │外进程  │ │  (D:\AKO工作流)   │
              │   chat)     │ │       │ │  ┌────retriever──┐│
              │ ❌ 绕过Hub  │ │❌绕过 │ │  │ 自己的RAG实现  ││
              └─────────────┘ └───────┘ │  │ ❌ 绕过Hub    ││
                                        │  └───────────────┘│
                                        └──────────────────┘

   ┌───────────── hub_api.py ─────────────┐
   │ submit_task() → Master Graph         │
   └──────────────┬───────────────────────┘
                  ▼
   ┌────────── master/graph.py ──────────────┐
   │ task_router → kb_allocator →            │
   │ workflow_caller → ... → sync_monitor    │
   └──────────────┬──────────────────────────┘
                  │ importlib 动态导入
                  ▼
   ┌──────── agents/ako_drawing_inspector.py ────┐
   │ subprocess → AKO_drawing_inspector/run.py   │
   │    → core/rag_engine.py:CodeRAG.search()    │
   │       → _hub_search()  ✅ 唯一 Hub 检索调用 │
   │       → _local_tfidf_search() (降级)        │
   └──────────────────────────────────────────────┘
                  │
                  ▼
   ┌────── core/knowledge_hub.py ──────────────┐
   │ KnowledgeHub.query()                       │
   │   → ChromaDB collection.query()            │
   │   ❌ 单向量 cosine distance，无混合检索     │
   └─────────────────────────────────────────────┘
```

### 3.2 各 Agent 检索路径详表

| # | Agent / 入口 | 检索方式 | 检索调用 | 经过 Hub? | 风险等级 |
|---|-------------|---------|---------|-----------|---------|
| 1 | `AKO_drawing_inspector` → `CodeRAG._hub_search()` | 向量检索 | `hub.query(kb_id="ako_taoli_building_codes_arch", query_text=query, n_results=top_k)` | ✅ 是 (唯一) | 🔴 P0 |
| 2 | `AKO_drawing_inspector` → `CodeRAG._local_tfidf_search()` | TF-IDF | 本地 sklearn TF-IDF | ❌ 否 | 🟢 降级方案 |
| 3 | `AKO_chat` → `RAGService.chat()` | 外部 RAG | `D:\AKO_chat\services\rag_service.py` | ❌ 否 | 🔴 P0 |
| 4 | `AKO工作流` → LangGraph `retriever` 节点 | 外部检索 | `D:\AKO工作流\graph.py` 内部实现 | ❌ 否 | 🔴 P0 |
| 5 | `AKO_architect_agent` | subprocess 外部进程 | `D:\AKO_architect_agent\run.py` | ❌ 否 | ⚠️ |
| 6 | `AKO_image_analyzer` | subprocess 外部进程 | `D:\AKO_image_analyzer\run.py` | ❌ 否 | ⚠️ |
| 7 | `web_ui → rag_chat()` | 间接 | → `ako_chat_adapter.run()` → 外部 RAGService | ❌ 否 | 🔴 P0 |
| 8 | `web_ui → analyze_image()` | 间接 | → `ako_image_analyzer.run()` → subprocess | ❌ 否 | ⚠️ |
| 9 | `web_ui → run_workflow()` | 间接 | → `ako_workflow_adapter.run()` → 外部 LangGraph | ❌ 否 | 🔴 P0 |
| 10 | `hub_api.submit_task()` | Hub 调度 | → Master Graph → workflow_caller → 外部 Agent | ❌ 否 | 🟡 |

### 3.3 唯一 Hub 检索调用点的深入分析

**文件**: `AKO_drawing_inspector/core/rag_engine.py` L277-310

```python
def _hub_search(self, query: str, top_k: int) -> List[Dict]:
    hub = _get_hub()
    if hub is None:
        return []
    try:
        results = hub.query(
            kb_id="ako_taoli_building_codes_arch",
            query_text=query,
            n_results=top_k,
        )
        # ...
        dists = results.get("distances", [[]])[0]
        for i, doc_id in enumerate(ids):
            similarity = 1.0 - dists[i] if i < len(dists) else 0.0
            output.append({
                "source": meta.get("source", doc_id),
                "content": docs[i] if i < len(docs) else "",
                "similarity": max(0.0, similarity),
            })
        return output
    except Exception as e:
        logger.warning(f"Hub 检索失败: {e}")
        return []
```

**升级后兼容性问题**:

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 未传 `retrieval_mode="hybrid"` | 🔴 P0 | KnowledgeHub 升级后若默认降级为 Dense-Only，损失 Sparse + ColBERT 精度 |
| 未传 `hybrid_weights` | 🔴 P0 | 无法自定义三路权重，默认权重可能不适用于规范条文检索场景 |
| `distance→similarity` 转换 | 🟡 P1 | `similarity = 1.0 - dists[i]`，升级后若返回 `final_scores`（已是相似度），转换会出错 |
| `kb_id` 硬编码 | 🟡 P1 | `"ako_taoli_building_codes_arch"` 需确认已通过 reembed_all.py 完成重建 |
| 异常静默降级到 TF-IDF | 🟡 P1 | 无告警级别区分，接口不兼容导致持续 fallback 到低精度 TF-IDF |
| 无检索超时控制 | 🟢 P2 | ColBERT 精排增加 200-600ms 延迟，需加 timeout 保护 |

---

## 4. 外部独立 RAG 栈风险

### 4.1 AKO_chat (`D:\AKO_chat\services\rag_service.py`)

```python
# agents/ako_chat_adapter.py L63-67
from services.rag_service import RAGService, RAGResponse
service = RAGService()
response = service.chat(message=user_question, kb_id=kb_id)
```

- `AKO_chat` 使用自己的 `RAGService`，与 Hub 完全解耦
- 即使 Hub 完成三向量升级，AKO_chat 不会自动受益
- web_ui.py 的 RAG 对话标签页 (`rag_chat()`) 通过此路径 → 用户面向的对话检索精度依赖外部项目

### 4.2 AKO工作流 (`D:\AKO工作流\graph.py`)

```python
# agents/ako_workflow_adapter.py L90-91
from graph import app
result = app.invoke(initial_state)
```

- retriever 节点在外部项目中实现，可能直接访问 ChromaDB 或自有 RAG 实现
- 设置了 `AKO_HUB_CHROMA_ROOT` 环境变量，说明会访问 Hub 的 ChromaDB 数据
- 但检索逻辑（单向量 vs 三向量）完全取决于外部项目代码

### 4.3 AKO_architect_agent / AKO_image_analyzer

- 通过 subprocess 调用外部独立进程，完全不经过 Hub
- 它们的检索能力取决于各自外部项目的实现

---

## 5. Master Graph 调度层

`master/nodes.py` 的 `kb_allocator` 节点只做注册校验：

```python
# master/nodes.py L169-191
def kb_allocator(state: MasterState) -> Dict[str, Any]:
    kb_ids = state.get("required_kb_ids", [])
    hub = KnowledgeHub(paths["db_path"], paths["chroma_root"])
    for kb_id in kb_ids:
        if not hub.is_kb_registered(kb_id):
            missing.append(kb_id)
```

- `kb_allocator` 只检查 `is_kb_registered()`（纯 SQL 查询），不涉及任何向量操作
- `workflow_caller` 通过 `importlib` 动态调用外部 Agent，不直接使用 KnowledgeHub 检索
- Master Graph 层与三向量升级**无直接兼容性冲突**

---

## 6. 接口差异汇总

| 项目 | KnowledgeHub (当前) | CodeRAG._hub_search() (唯一调用者) | 差异 |
|------|---------------------|----------------------------------|------|
| 检索函数 | `query(kb_id, query_text, n_results, where, where_document)` | `hub.query(kb_id=..., query_text=query, n_results=top_k)` | ✅ 参数兼容 |
| `retrieval_mode` | **不存在** | **未传入** | 🔴 升级后需新增 |
| `hybrid_weights` | **不存在** | **未传入** | 🔴 升级后需新增 |
| 返回值: `distances` | ✅ ChromaDB cosine distance | `similarity = 1.0 - dists[i]` | 🟡 升级后优先用 `final_scores` |
| 返回值: `final_scores` | ❌ 不存在 | ❌ 未读取 | 🔴 升级后核心字段 |
| 返回值: `dense_scores` | ❌ 不存在 | ❌ 未读取 | 🟢 调试字段 |
| 返回值: `sparse_scores` | ❌ 不存在 | ❌ 未读取 | 🟢 调试字段 |
| 返回值: `colbert_scores` | ❌ 不存在 | ❌ 未读取 | 🟢 调试字段 |
| top_k 默认值 | `5` | 由 `settings.yaml: rag.top_k` (=3) 控制 | ✅ 正常 |
| kb_id | — | `"ako_taoli_building_codes_arch"` 硬编码 | 🟡 需确认已重建 |
| embedding_model | `"nomic-embed-text"` | — | 🔴 配置层仍为旧值 |

---

## 7. 风险清单

### 🔴 P0 — 必改（否则检索能力不升反降）

| # | 风险 | 涉及文件 | 说明 |
|---|------|---------|------|
| P0-1 | **KnowledgeHub.query() 未实现三向量检索** | `core/knowledge_hub.py` | 数据已写入 sparse/colbert metadata，但查询路径仍是单向量 cosine distance。需实现：Sparse 词权重查询 + ColBERT Token-Level 精排 + RRF 融合 |
| P0-2 | **embedding_model 配置仍是 nomic-embed-text** | `config/hub.yaml` L25 | reembed_all.py 已写入 bge-m3 向量，但配置文件未同步更新 |
| P0-3 | **CodeRAG 未传 hybrid 参数** | `AKO_drawing_inspector/core/rag_engine.py` L284-288 | 升级后若默认 Dense-Only，图纸规范检索精度大幅下降 |
| P0-4 | **AKO_chat 独立 RAG 栈未升级** | `D:\AKO_chat\services\rag_service.py` | web_ui RAG 对话标签页完全依赖此外部项目，需独立升级或改道 Hub |
| P0-5 | **AKO工作流 retriever 节点未升级** | `D:\AKO工作流\graph.py` | 外部项目检索节点需确认兼容性 |
| P0-6 | **KnowledgeHub.__init__ 默认模型错误** | `core/knowledge_hub.py` L64 | `embedding_model: str = "nomic-embed-text"` 应改为 `"bge-m3"` |

### 🟡 P1 — 建议改（否则精度下降或静默降级）

| # | 风险 | 涉及文件 |
|---|------|---------|
| P1-1 | CodeRAG score 字段语义不兼容 `final_scores` | `rag_engine.py` L299 |
| P1-2 | CodeRAG kb_id 硬编码需确认重建 | `rag_engine.py` L286 |
| P1-3 | 异常时静默降级到 TF-IDF 无告警级别 | `rag_engine.py` L309 |
| P1-4 | `settings.yaml` embedding_model 未更新 | `AKO_drawing_inspector/config/settings.yaml` |
| P1-5 | Query 构造未针对 Hybrid 优化（Prompt 层） | `analysis_v1.txt` |
| P1-6 | `query()` 返回值缺少 `final_scores` 等新字段 | `core/knowledge_hub.py` |
| P1-7 | 无断点续传/增量 reembed 机制 | `reembed_all.py` |

### 🟢 P2 — 可选优化

| # | 风险 | 涉及文件 |
|---|------|---------|
| P2-1 | 检索无超时控制（ColBERT 增加延迟） | `rag_engine.py` L277 |
| P2-2 | 无检索结果缓存机制 | 全局 |
| P2-3 | 并发检索无 GPU 显存控制 | 全局 |

---

## 8. 最小修复方案

### Phase 0: KnowledgeHub 完成三向量查询（核心）

**文件**: `core/knowledge_hub.py`

需新增/修改：

```python
class KnowledgeHub:
    def __init__(self, ..., retrieval_mode: str = "hybrid",
                 hybrid_weights: Dict[str, float] = None):
        # 新增参数
        self.retrieval_mode = retrieval_mode
        self.hybrid_weights = hybrid_weights or {"dense": 0.33, "sparse": 0.33, "colbert": 0.34}
    
    def query(self, kb_id, query_text, n_results=5,
              retrieval_mode=None, hybrid_weights=None, ...):
        # 1. Dense: ChromaDB 原生 query (已有)
        # 2. Sparse: 从 metadata.sparse_lexicon 中做词权重匹配
        # 3. ColBERT: 加载 metadata.colbert_tokens 做 Late Interaction
        # 4. RRF 融合三路分数
        # 5. 返回结果中包含 final_scores
```

### Phase 1: CodeRAG 适配新接口

**文件**: `AKO_drawing_inspector/core/rag_engine.py` L277-310

```diff
     def _hub_search(self, query: str, top_k: int) -> List[Dict]:
         hub = _get_hub()
         if hub is None:
             return []
         try:
             results = hub.query(
                 kb_id="ako_taoli_building_codes_arch",
                 query_text=query,
                 n_results=top_k,
+                retrieval_mode="hybrid",
+                hybrid_weights={"dense": 0.33, "sparse": 0.33, "colbert": 0.34},
             )
             # ...
+            if "final_scores" in results:
+                scores = results["final_scores"][0]
+            else:
+                dists = results.get("distances", [[]])[0]
+                scores = [1.0 - d for d in dists]
             for i, doc_id in enumerate(ids):
-                similarity = 1.0 - dists[i] if i < len(dists) else 0.0
+                score = scores[i] if i < len(scores) else 0.0
                 output.append({
                     "source": meta.get("source", doc_id),
                     "content": docs[i] if i < len(docs) else "",
-                    "similarity": max(0.0, similarity),
+                    "similarity": max(0.0, score),
                 })
             return output
         except Exception as e:
-            logger.warning(f"Hub 检索失败: {e}")
+            logger.warning(f"Hub 检索失败，降级到 TF-IDF: {e}")
             return []
```

### Phase 2: 配置更新

**config/hub.yaml**:
```yaml
embedding_model: "bge-m3"
retrieval_mode: "hybrid"
hybrid_weights:
  dense: 0.33
  sparse: 0.33
  colbert: 0.34
colbert_rerank_top_k: 20
```

**AKO_drawing_inspector/config/settings.yaml**:
```yaml
rag:
  embedding_model: "bge-m3"
  retrieval_mode: "hybrid"
  hybrid_weights:
    dense: 0.33
    sparse: 0.33
    colbert: 0.34
```

### Phase 3: Prompt 微调

**AKO_drawing_inspector/prompts/analysis_v1.txt**:
```
在查询相关规范时，请同时提供关键词列表和自然语言问题描述，
以充分利用混合检索（关键词精确匹配 + 语义相似度）的双重优势。
```

### Phase 4: 外部项目对齐（分批）

| 优先级 | 外部项目 | 行动 |
|--------|---------|------|
| 🔴 P0 | `D:\AKO_chat` | 更新 RAGService，支持 bge-m3 三向量，或改为调用 Hub KnowledgeHub |
| 🔴 P0 | `D:\AKO工作流` | 确认 retriever 节点检索实现，更新为 bge-m3 或改为调用 Hub |
| 🟡 P1 | `D:\AKO_architect_agent` | 评估检索路径，如需混合检索则改为调用 Hub |
| 🟡 P1 | `D:\AKO_image_analyzer` | 评估检索路径，如需混合检索则改为调用 Hub |

---

## 9. 结论

1. **三向量升级处于"数据已写入但查询未使用"的半完成状态**：`scripts/reembed_all.py` 已将 bge-m3 三向量写入 ChromaDB metadata（`sparse_lexicon` / `colbert_tokens`），但 `core/knowledge_hub.py` 的 `query()` 方法完全未读取这些字段，仍然是 ChromaDB 原生单向量 cosine distance 查询。

2. **唯一经过 Hub 检索的调用点是 `AKO_drawing_inspector` 的 `CodeRAG._hub_search()`**，其余 4 个 Agent (`AKO_chat`、`AKO工作流`、`AKO_architect_agent`、`AKO_image_analyzer`) 使用外部独立 RAG 栈，即使 Hub 完成升级也不会受益。

3. **最紧急任务**：实现 `KnowledgeHub.query()` 的三向量融合查询逻辑（Sparse 词权重 + ColBERT 精排 + RRF），这是让已有数据产生价值的唯一路径。

4. **其次紧急**：更新 `CodeRAG._hub_search()` 调用签名，适配新接口的参数和返回值。

5. **长期建设**：推动外部 Agent 项目统一通过 Hub KnowledgeHub 检索，避免各自维护独立的、版本不一致的 RAG 实现。

---

**审查人**: Cline AI  
**审查完成时间**: 2026-06-30 08:30 UTC+8