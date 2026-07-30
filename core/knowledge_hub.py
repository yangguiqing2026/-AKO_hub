"""
AKO Hub — 知识库统一路由层
KnowledgeHub: 封装 Chroma 访问，统一 Collection 命名与检索接口。

文档编号: AGE-TECH-AKO-HUB-001 §4
"""

import re
import time
import hashlib
from pathlib import Path
from collections import OrderedDict
from typing import Optional, List, Dict, Any

from core.hub_db import HubDB

# chromadb 延迟导入：仅在需要访问向量库时加载
_CHROMA_AVAILABLE = False
try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore


# ── 命名规范（强制） ─────────────────────────────────────────────
# collection_name = ako_{project_tag}_{kb_type}_{agent_short}
_COLLECTION_RE = re.compile(r"^ako_[a-z0-9]+_[a-z0-9]+_[a-z0-9]+$")


def _agent_short(agent_name: str) -> str:
    """
    将 Agent 全称压缩为 4 字符短码。
    规则：去掉 "ako_" 前缀，忽略末尾 "agent" 等通用后缀，取最后一个有意义的词前 4 字母。
    例：AKO_architect_agent → arch
         AKO_drawing_inspector → insp
         AKO_image_analyzer → anal
    """
    parts = agent_name.lower().replace("ako_", "").split("_")
    # 过滤掉 "agent" 等通用后缀，取最后一个有效词
    skip_words = {"agent", "workflow", "node"}
    meaningful = [p for p in parts if p and p not in skip_words]
    core = meaningful[-1] if meaningful else "unk"
    return core[:4]


def make_collection_name(project_tag: str, kb_type: str, agent_name: str) -> str:
    """按照白皮书命名规范生成 Collection 名。"""
    short = _agent_short(agent_name)
    return f"ako_{project_tag}_{kb_type}_{short}"


class KnowledgeHub:
    """
    知识库统一路由层。

    职责：
    1. 所有 Spoke 不得直接访问 chromadb.Client，必须经此接口。
    2. Collection 名称由本类按规范统一生成，禁止 Spoke 自定义。
    3. 全局 embedding_model 锁定为 bge-m3（三向量 Dense+Sparse+ColBERT）。

    使用：
        hub = KnowledgeHub(db_path="/path/to/age_hub.db", chroma_root="/path/to/chroma_db")
        results = hub.query("ako_tech_struct", "查询文本", retrieval_mode="hybrid")
    """

    # 默认混合检索权重
    DEFAULT_HYBRID_WEIGHTS = {"dense": 0.33, "sparse": 0.33, "colbert": 0.34}

    def __init__(
        self,
        db_path: str,
        chroma_root: str,
        embedding_model: str = "bge-m3",
        retrieval_mode: str = "hybrid",
        hybrid_weights: Optional[Dict[str, float]] = None,
        colbert_rerank_top_k: int = 20,
        cache_size: int = 128,
        cache_ttl: int = 300,
    ):
        self.db = HubDB(db_path)
        self.chroma_root = Path(chroma_root).resolve()
        self.embedding_model = embedding_model
        self.retrieval_mode = retrieval_mode
        self.hybrid_weights = hybrid_weights or self.DEFAULT_HYBRID_WEIGHTS
        self.colbert_rerank_top_k = colbert_rerank_top_k
        # Chroma PersistentClient 懒加载：首次 get_collection 时创建
        self._client: Optional[Any] = None
        # 自动建表（幂等）
        self.db.connect()
        self.db.init_schema()
        self.db.close()
        # LRU 查询缓存
        self._cache: OrderedDict[str, tuple[float, Dict[str, Any]]] = OrderedDict()
        self._cache_max_size = cache_size
        self._cache_ttl = cache_ttl
        self._cache_hits = 0
        self._cache_misses = 0

    # ── 缓存辅助 ────────────────────────────────────────────────────

    def _cache_key(self, kb_id: str, query_text: str, n_results: int,
                   retrieval_mode: str, where: Optional[Dict],
                   where_document: Optional[Dict]) -> str:
        raw = f"{kb_id}||{query_text}||{n_results}||{retrieval_mode}||{where}||{where_document}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _invalidate_cache(self, kb_id: Optional[str] = None) -> None:
        if kb_id is None:
            self._cache.clear()
        else:
            prefix = hashlib.md5(f"{kb_id}||".encode("utf-8")).hexdigest()[:8]
            stale_keys = [k for k in self._cache if k.startswith(prefix)]
            for k in stale_keys:
                del self._cache[k]

    @property
    def cache_stats(self) -> dict:
        total = self._cache_hits + self._cache_misses
        return {
            "size": len(self._cache),
            "max_size": self._cache_max_size,
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": round(self._cache_hits / total, 4) if total > 0 else 0.0,
            "ttl_seconds": self._cache_ttl,
        }

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    # ── Chroma 客户端懒加载 ──────────────────────────────────────

    def _ensure_client(self) -> Any:
        if not _CHROMA_AVAILABLE:
            raise ImportError(
                "chromadb 未安装。请执行: pip install chromadb\n"
                "提示：P0 阶段仅注册知识库无需 chromadb，实际向量操作时需要。"
            )
        if self._client is None:
            self.chroma_root.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.chroma_root))  # type: ignore
        return self._client

    # ── 注册（仅 Master / 管理员调用） ────────────────────────────

    def register_kb(self, kb_id: str, kb_name: str, agent_name: str,
                    project_tag: str, kb_type: str,
                    vector_db_path: str = None, description: str = "") -> str:
        """
        注册知识库到元数据表，并返回生成的 collection_name。
        若 collection_name 已存在，则直接返回已注册的名称。
        """
        collection_name = make_collection_name(project_tag, kb_type, agent_name)

        # 校验命名规范
        if not _COLLECTION_RE.match(collection_name):
            raise ValueError(f"Collection 命名非法: {collection_name}")

        # 确定向量库路径（默认放在 chroma_root 下）
        if vector_db_path is None:
            vector_db_path = str(self.chroma_root / collection_name)
        else:
            vector_db_path = str(Path(vector_db_path).resolve())

        with self.db:
            existing = self.db.fetchone(
                "SELECT collection_name FROM knowledge_base WHERE kb_id=?",
                (kb_id,),
            )
            if existing:
                return existing["collection_name"]

            self.db.execute(
                """INSERT INTO knowledge_base
                   (kb_id, kb_name, agent_name, collection_name, embedding_model, vector_db_path, description)
                   VALUES (?,?,?,?,?,?,?)""",
                (kb_id, kb_name, agent_name, collection_name,
                 self.embedding_model, vector_db_path, description),
            )
        return collection_name

    # ── 注册查询（不依赖 chromadb） ───────────────────────────────

    def is_kb_registered(self, kb_id: str) -> bool:
        """仅查元数据表，判断知识库是否已注册。不触发 Chroma 连接。"""
        with self.db:
            row = self.db.fetchone("SELECT 1 FROM knowledge_base WHERE kb_id=?", (kb_id,))
        return row is not None

    # ── 获取 Collection（Spoke 调用） ─────────────────────────────

    def get_collection(self, kb_id: str) -> Any:
        """根据 kb_id 查元数据，返回 Chroma Collection 对象。"""
        with self.db:
            row = self.db.fetchone(
                "SELECT collection_name, vector_db_path FROM knowledge_base WHERE kb_id=?",
                (kb_id,),
            )
        if not row:
            raise ValueError(f"知识库 {kb_id} 未在元数据中注册")

        client = self._ensure_client()
        return client.get_or_create_collection(name=row["collection_name"])

    # ── 统一检索 ──────────────────────────────────────────────────

    def query(
        self,
        kb_id: str,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None,
        retrieval_mode: Optional[str] = None,
        hybrid_weights: Optional[Dict[str, float]] = None,
        return_details: bool = False,
    ) -> Dict[str, Any]:
        """
        在指定知识库中执行向量检索。

        支持三种检索模式：
        - "hybrid":      Dense + Sparse (metadata) + ColBERT 精排 → RRF 融合（默认）
        - "dense_only":  ChromaDB 原生 Dense 检索（降级兼容旧版）
        - "sparse_only": 仅 sparse lexicon 词权重匹配

        Args:
            kb_id:           知识库 ID
            query_text:      查询文本
            n_results:       返回条数
            where:           metadata 过滤条件
            where_document:  文档内容过滤条件
            retrieval_mode:  检索模式 ("hybrid" | "dense_only" | "sparse_only")
            hybrid_weights:  三路权重 {"dense": 0.33, "sparse": 0.33, "colbert": 0.34}
            return_details:  是否返回各路分数明细

        Returns:
            {
                "ids":           [["id1", "id2", ...]],
                "documents":     [["doc1", "doc2", ...]],
                "metadatas":     [[{...}, {...}, ...]],
                "distances":     [[0.1, 0.2, ...]],      # 向后兼容，越大越不相似
                "similarities":  [[0.9, 0.8, ...]],      # 新增，越大越相似
                "final_scores":  [[0.87, 0.76, ...]],    # RRF 融合 + 精排后分数 [0,1]
                "dense_scores":  [[0.85, ...]],          # 仅 return_details=True
                "sparse_scores": [[0.72, ...]],          # 仅 return_details=True
                "colbert_scores":[[0.91, ...]],          # 仅 return_details=True
                "retrieval_mode": "hybrid",
            }
        """
        mode = retrieval_mode or self.retrieval_mode
        weights = hybrid_weights or self.hybrid_weights

        # LRU 缓存查找
        cache_key = self._cache_key(kb_id, query_text, n_results, mode, where, where_document)
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                self._cache.move_to_end(cache_key)
                self._cache_hits += 1
                return cached
            else:
                del self._cache[cache_key]

        self._cache_misses += 1

        if mode == "dense_only":
            result = self._dense_query(kb_id, query_text, n_results, where, where_document)
        elif mode == "sparse_only":
            result = self._sparse_query(kb_id, query_text, n_results)
        else:
            result = self._hybrid_query(
                kb_id, query_text, n_results, where, where_document,
                weights, return_details,
            )

        # 写入缓存
        if len(self._cache) >= self._cache_max_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[cache_key] = (time.time(), result)
        self._cache.move_to_end(cache_key)

        return result

    def _dense_query(
        self, kb_id: str, query_text: str, n_results: int,
        where: Optional[Dict], where_document: Optional[Dict],
    ) -> Dict[str, Any]:
        """ChromaDB 原生 Dense 检索（兼容旧版）。"""
        col = self.get_collection(kb_id)
        result = col.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
            where_document=where_document,
        )
        # 补上向后兼容字段
        result["similarities"] = self._distances_to_similarities(result.get("distances"))
        result["final_scores"] = result["similarities"]
        result["retrieval_mode"] = "dense_only"
        return result

    def _hybrid_query(
        self, kb_id: str, query_text: str, n_results: int,
        where: Optional[Dict], where_document: Optional[Dict],
        weights: Dict[str, float], return_details: bool,
    ) -> Dict[str, Any]:
        """
        三向量混合检索：
        1. Dense: ChromaDB 原生查询，召回 top 候选
        2. Sparse: 对候选文档的 metadata.sparse_lexicon 做词权重匹配
        3. ColBERT: 对候选文档的 metadata.colbert_tokens 做 Late Interaction 精排
        4. RRF 加权融合三路分数
        """
        col = self.get_collection(kb_id)

        # 1. Dense: 召回足够多的候选（ColBERT 精排需要的候选集）
        candidate_k = max(n_results, self.colbert_rerank_top_k)
        dense_result = col.query(
            query_texts=[query_text],
            n_results=candidate_k,
            where=where,
            where_document=where_document,
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        if not dense_result or not dense_result.get("ids") or not dense_result["ids"][0]:
            return dense_result

        ids = dense_result["ids"][0]
        documents = dense_result.get("documents", [[]])[0]
        metadatas = dense_result.get("metadatas", [[]])[0]
        dense_distances = dense_result.get("distances", [[]])[0]

        # 2. Dense 分数：distance → similarity
        dense_scores = [max(0.0, 1.0 - d) for d in dense_distances]

        # 3. Sparse: 读取候选人 metadata 中的 sparse_lexicon，做词权重匹配
        sparse_scores = self._compute_sparse_scores(query_text, metadatas)

        # 4. ColBERT: Late Interaction 精排（仅对有效的候选）
        colbert_scores = self._compute_colbert_scores(
            query_text, documents, metadatas, ids
        )

        # 5. RRF 加权融合
        n = len(ids)
        final_scores = self._rrf_fuse(
            dense_scores, sparse_scores, colbert_scores,
            weights, n,
        )

        # 按 final_scores 重排并截断到 n_results
        ranked = sorted(
            zip(ids, documents, metadatas, final_scores, dense_scores, sparse_scores, colbert_scores),
            key=lambda x: x[3], reverse=True,
        )[:n_results]

        out_ids, out_docs, out_metas, out_final, out_dense, out_sparse, out_colbert = (
            zip(*ranked) if ranked else ([], [], [], [], [], [], [])
        )

        result: Dict[str, Any] = {
            "ids": [list(out_ids)],
            "documents": [list(out_docs)],
            "metadatas": [list(out_metas)],
            "distances": [[1.0 - s for s in out_final]],  # 向后兼容
            "similarities": [list(out_final)],
            "final_scores": [list(out_final)],
            "retrieval_mode": "hybrid",
        }

        if return_details:
            result["dense_scores"] = [list(out_dense)]
            result["sparse_scores"] = [list(out_sparse)]
            result["colbert_scores"] = [list(out_colbert)]

        return result

    def _sparse_query(
        self, kb_id: str, query_text: str, n_results: int,
    ) -> Dict[str, Any]:
        """仅 Sparse 词权重匹配检索。"""
        col = self.get_collection(kb_id)
        candidate_k = max(n_results, self.colbert_rerank_top_k)
        all_data = col.get(
            limit=candidate_k,
            include=["documents", "metadatas"],
        )

        ids = all_data.get("ids", [])
        documents = all_data.get("documents", [])
        metadatas = all_data.get("metadatas", [])

        if not ids:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]],
                    "distances": [[]], "similarities": [[]],
                    "final_scores": [[]], "retrieval_mode": "sparse_only"}

        sparse_scores = self._compute_sparse_scores(query_text, metadatas)

        ranked = sorted(
            zip(ids, documents, metadatas, sparse_scores),
            key=lambda x: x[3], reverse=True,
        )[:n_results]

        out_ids, out_docs, out_metas, out_scores = (
            zip(*ranked) if ranked else ([], [], [], [])
        )

        return {
            "ids": [list(out_ids)],
            "documents": [list(out_docs)],
            "metadatas": [list(out_metas)],
            "distances": [[1.0 - s for s in out_scores]],
            "similarities": [list(out_scores)],
            "final_scores": [list(out_scores)],
            "retrieval_mode": "sparse_only",
        }

    # ── 三向量内部算法 ──────────────────────────────────────────

    def _compute_sparse_scores(
        self, query_text: str, metadatas: List[Dict[str, Any]],
    ) -> List[float]:
        """
        计算查询与每个候选文档的 Sparse 匹配得分。

        策略：对查询文本做简单 jieba 分词 / 字符级分词，
        与 metadata 中预存的 sparse_lexicon (JSON: {token_id: weight}) 做内积。
        如果 sparse_lexicon 缺失，返回 0.0。
        """
        if not metadatas:
            return []

        # 查询分词：使用字符级 bigram 作为轻量 sparse token
        query_tokens = self._tokenize_sparse(query_text)
        scores = []
        for meta in metadatas:
            meta = meta or {}
            raw = meta.get("sparse_lexicon")
            if not raw:
                scores.append(0.0)
                continue

            try:
                import json
                lexicon = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                scores.append(0.0)
                continue

            # 内积：Σ(token_id 在查询中出现 ? lexicon_weight : 0)
            score = 0.0
            for token in query_tokens:
                token_str = str(token)
                w = lexicon.get(token_str, 0.0)
                score += float(w)
            scores.append(score)

        return scores

    def _compute_colbert_scores(
        self, query_text: str, documents: List[str],
        metadatas: List[Dict[str, Any]], ids: List[str],
    ) -> List[float]:
        """
        ColBERT Late Interaction 精排。

        策略：从 metadata.colbert_tokens (JSON: [[float]*1024, ...] multi-vector)
        加载候选人 token embeddings，与查询 token embeddings 做 MaxSim 计算。
        如果 colbert_tokens 缺失，返回 0.0。
        """
        n = len(ids)
        if n == 0:
            return []

        # 尝试加载候选人的 colbert tokens
        all_colbert = []
        for meta in metadatas:
            meta = meta or {}
            raw = meta.get("colbert_tokens")
            if not raw:
                all_colbert.append(None)
                continue
            try:
                import json
                tokens = json.loads(raw) if isinstance(raw, str) else raw
                all_colbert.append(tokens)
            except (json.JSONDecodeError, TypeError):
                all_colbert.append(None)

        # 如果全部缺失 colbert_tokens，返回 0.0
        if all(v is None for v in all_colbert):
            return [0.0] * n

        # 查询 token embeddings（用字符级近似）
        query_embs = self._encode_query_colbert(query_text)
        if query_embs is None or len(query_embs) == 0:
            return [0.0] * n

        scores = []
        for colbert_tokens in all_colbert:
            if colbert_tokens is None or len(colbert_tokens) == 0:
                scores.append(0.0)
                continue

            # MaxSim: 对每个 query token，找 doc token 中最大余弦相似度，求和
            try:
                # [FINAL_CLEAN] import numpy as np
                doc_vecs = np.array(colbert_tokens, dtype=np.float32)
                query_vecs = np.array(query_embs, dtype=np.float32)

                # 归一化
                doc_norm = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-8)
                query_norm = query_vecs / (np.linalg.norm(query_vecs, axis=1, keepdims=True) + 1e-8)

                # MaxSim: Σ_{q} max_{d} (q·d)
                sim_matrix = np.dot(query_norm, doc_norm.T)  # (Q, D)
                maxsim = np.max(sim_matrix, axis=1).sum() / max(len(query_vecs), 1)
                scores.append(float(maxsim))
            except Exception:
                scores.append(0.0)

        return scores

    def _rrf_fuse(
        self,
        dense_scores: List[float],
        sparse_scores: List[float],
        colbert_scores: List[float],
        weights: Dict[str, float],
        n: int,
    ) -> List[float]:
        """
        RRF (Reciprocal Rank Fusion) 加权融合。

        1. 三路分别排名
        2. 对每条文档：final = Σ w_i / (k + rank_i)   (k=60)
        3. 归一化到 [0, 1]
        """
        # [FINAL_CLEAN] import numpy as np

        def scores_to_ranks(scores: List[float]) -> List[int]:
            """分数越高排名越靠前（rank 从 1 开始）。"""
            order = np.argsort(scores)[::-1]
            ranks = [0] * len(scores)
            for r, idx in enumerate(order):
                ranks[idx] = r + 1
            return ranks

        dense_ranks = scores_to_ranks(dense_scores) if any(s > 0 for s in dense_scores) else [n] * n
        sparse_ranks = scores_to_ranks(sparse_scores) if any(s > 0 for s in sparse_scores) else [n] * n
        colbert_ranks = scores_to_ranks(colbert_scores) if any(s > 0 for s in colbert_scores) else [n] * n

        k = 60.0
        w_d = weights.get("dense", 0.33)
        w_s = weights.get("sparse", 0.33)
        w_c = weights.get("colbert", 0.34)

        fused = []
        for i in range(n):
            score = (
                w_d / (k + dense_ranks[i]) +
                w_s / (k + sparse_ranks[i]) +
                w_c / (k + colbert_ranks[i])
            )
            fused.append(score)

        # 归一化到 [0, 1]
        arr = np.array(fused)
        if arr.max() > arr.min():
            arr = (arr - arr.min()) / (arr.max() - arr.min())
        else:
            arr = np.ones_like(arr) * 0.5

        return arr.tolist()

    # ── 轻量分词 / 编码工具 ──────────────────────────────────────

    @staticmethod
    def _tokenize_sparse(text: str) -> List[str]:
        """字符级 bigram + unigram 分词（轻量 sparse token）。"""
        text = text.strip().lower()
        if not text:
            return []
        tokens = []
        # unigram
        tokens.extend(text)
        # bigram
        for i in range(len(text) - 1):
            tokens.append(text[i:i + 2])
        # 中文分词增强（可选 jieba）
        try:
            import jieba
            tokens.extend(jieba.lcut(text))
        except ImportError:
            pass
        return list(set(tokens))

    @staticmethod
    def _encode_query_colbert(query_text: str) -> Optional[List[List[float]]]:
        """
        为 ColBERT 精排生成查询文本的 token embeddings。

        优先使用 FlagEmbedding，降级到 Ollama，再降级到随机向量。
        返回: [[float]*dim, ...]
        """
        try:
            from FlagEmbedding import BGEM3FlagModel
            # 懒加载单例
            if not hasattr(KnowledgeHub, "_flag_model_cache"):
                KnowledgeHub._flag_model_cache = BGEM3FlagModel(
                    "BAAI/bge-m3", use_fp16=False, device="cpu",
                )
            model = KnowledgeHub._flag_model_cache
            output = model.encode(
                [query_text],
                batch_size=1,
                return_dense=False,
                return_sparse=False,
                return_colbert_vecs=True,
            )
            colbert = output.get("colbert_vecs", [])
            if colbert and len(colbert) > 0:
                c = colbert[0]
                return c.tolist() if hasattr(c, "tolist") else list(c)
        except Exception:
            pass

        # Ollama 降级：生成 dense 向量后当做单 token colbert
        try:
            import ollama
            r = ollama.embeddings(model="bge-m3", prompt=query_text[:8000])
            emb = r.get("embedding", [])
            if emb:
                return [emb]
        except Exception:
            pass

        # 最终降级：随机 1024-dim 向量
        import random
        random.seed(hash(query_text) % (2**31))
        return [[random.random() for _ in range(1024)]]

    @staticmethod
    def _distances_to_similarities(distances: Optional[List[List[float]]]) -> List[List[float]]:
        """ChromaDB cosine distance → 归一化相似度。"""
        if not distances or not distances[0]:
            return [[]]
        return [[max(0.0, 1.0 - d) for d in distances[0]]]

    # ── 统一写入 ──────────────────────────────────────────────────

    def upsert(self, kb_id: str, ids: List[str], documents: List[str],
               metadatas: Optional[List[Dict[str, Any]]] = None,
               embeddings: Optional[List[List[float]]] = None) -> None:
        """向指定知识库批量写入或更新文档。"""
        col = self.get_collection(kb_id)
        col.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        self._invalidate_cache(kb_id)

    def add(self, kb_id: str, ids: List[str], documents: List[str],
            metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        """增量添加（不覆盖已有 id）。"""
        col = self.get_collection(kb_id)
        col.add(ids=ids, documents=documents, metadatas=metadatas)
        self._invalidate_cache(kb_id)

    def delete(self, kb_id: str, ids: Optional[List[str]] = None,
               where: Optional[Dict[str, Any]] = None) -> None:
        """按 id 或条件删除。"""
        col = self.get_collection(kb_id)
        col.delete(ids=ids, where=where)
        self._invalidate_cache(kb_id)

    # ── 列表查询 ──────────────────────────────────────────────────

    def list_kb_by_agent(self, agent_name: str) -> List[Dict[str, Any]]:
        """返回某 Agent 的所有知识库注册信息。"""
        with self.db:
            return self.db.fetchall(
                "SELECT * FROM knowledge_base WHERE agent_name=? ORDER BY updated_at DESC",
                (agent_name,),
            )

    def list_kb_by_project(self, project_tag: str) -> List[Dict[str, Any]]:
        """返回某项目下的所有知识库（通过 collection_name 前缀匹配）。"""
        pattern = f"ako_{project_tag}_%"
        with self.db:
            return self.db.fetchall(
                "SELECT * FROM knowledge_base WHERE collection_name LIKE ? ORDER BY updated_at DESC",
                (pattern,),
            )

    def list_all_kb(self) -> List[Dict[str, Any]]:
        """返回全部知识库。"""
        with self.db:
            return self.db.fetchall("SELECT * FROM knowledge_base ORDER BY updated_at DESC")
