#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AKO Hub 全库重 embedding 脚本
================================

用途:
    把所有 ChromaDB collection 的向量从旧模型 (nomic-embed-text / MiniLM)
    迁移到 bge-m3 (Dense 1024-dim)，并附加 sparse_lexicon / colbert_tokens
    hybrid metadata，让 AKO_Hub 的 KnowledgeHub.query() 能直接启用三向量检索。

流程 (对每个 collection):
    1. 备份原 collection 到 chroma_db_backup/{collection_name}_{timestamp}/
    2. 分批 get() 取出所有 (ids, documents, metadatas)
    3. 用 bge-m3 重新编码 dense embedding (FlagEmbedding 优先，Ollama 降级)
    4. 用 build_hybrid_metadata() 重写 sparse_lexicon / colbert_tokens
    5. upsert() 覆盖原 collection
    6. 更新 hub_meta.db 中 knowledge_base.embedding_model 为 bge-m3

用法:
    # 先 dry-run 看看会动哪些 collection、多少文档
    python scripts/reembed_all.py --dry-run

    # 真跑 (默认带备份)
    python scripts/reembed_all.py

    # 指定 collection (可多次)
    python scripts/reembed_all.py --collection ako_taoli_general_arch

    # 强制使用 Ollama 而不用本地 FlagEmbedding
    python scripts/reembed_all.py --backend ollama

    # 不备份直接跑 (不推荐)
    python scripts/reembed_all.py --no-backup

    # 只备份不重写 (用于灾备)
    python scripts/reembed_all.py --backup-only

    # metadata-only: 保留原 dense embedding (已经是 bge-m3 1024-dim)，
    # 只补 sparse_lexicon / colbert_tokens hybrid metadata。速度极快，无需加载 FlagEmbedding / Ollama。
    python scripts/reembed_all.py --metadata-only --chroma-root "D:/AKO_knowledge" --no-update-db

依赖:
    pip install chromadb numpy tqdm
    # 推荐 (完整三向量):
    pip install FlagEmbedding torch
    # 或用 Ollama (dense only，sparse/colbert 由 build_hybrid_metadata 用分词近似):
    # 安装 Ollama 并拉模型: ollama pull bge-m3

兼容性:
    Windows / Linux / macOS, Python 3.10+
    依赖 AKO_knowledge/hybrid_retrieval.py 的 build_hybrid_metadata()
    依赖 AKO_Hub/core/knowledge_hub.py 的 KnowledgeHub

作者: AKO 团队 · 2026-06
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 路径注入（让本脚本可以从 scripts/ 目录或任意位置运行） ────────
HERE = Path(__file__).resolve().parent
HUB_ROOT = HERE.parent.resolve()
KNOWLEDGE_ROOT = Path("D:/AKO_knowledge").resolve()

if str(HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(HUB_ROOT))
if str(KNOWLEDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_ROOT))

# ── 第三方导入 ──────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
except ImportError:
    sys.exit("❌ chromadb 未安装，请执行: pip install chromadb")

try:
    from tqdm import tqdm
except ImportError:
    # 轻量降级
    def tqdm(it, **_):
        return it

# ── AKO 内部模块 ─────────────────────────────────────────────────
try:
    from core.knowledge_hub import KnowledgeHub
    from core.hub_db import HubDB
except ImportError as e:
    sys.exit(f"❌ 无法导入 AKO_Hub.core: {e}\n请确认脚本从 D:\\AKO_Hub 目录或带完整路径运行")

try:
    from hybrid_retrieval import build_hybrid_metadata
except ImportError as e:
    sys.exit(f"❌ 无法导入 AKO_knowledge.hybrid_retrieval: {e}\n请确认 D:\\AKO_knowledge 在 PYTHONPATH 中")


# ══════════════════════════════════════════════════════════════════
# 1. Embedding 后端 (bge-m3)
# ══════════════════════════════════════════════════════════════════

class BgeM3Encoder:
    """
    bge-m3 编码器封装。优先 FlagEmbedding (完整三向量)，
    不可用时降级到 Ollama (dense only，sparse/colbert 留给 build_hybrid_metadata)。
    """

    def __init__(self, backend: str = "auto", batch_size: int = 16,
                 model_path: str = "BAAI/bge-m3"):
        self.backend = backend
        self.batch_size = batch_size
        self.model_path = model_path
        self._flag_model = None
        self._ollama_model = "bge-m3"
        self._init_backend()

    def _init_backend(self) -> None:
        if self.backend in ("auto", "flag"):
            try:
                from FlagEmbedding import BGEM3FlagModel
                print(f"🚀 加载 BGEM3FlagModel (本地 GPU/CPU)...")
                print(f"   模型路径: {self.model_path}")
                self._flag_model = BGEM3FlagModel(
                    self.model_path,
                    use_fp16=False,  # CPU 不支持 fp16
                    device="cpu",
                )
                self.backend = "flag"
                print(f"   ✅ FlagEmbedding 三向量后端就绪")
                return
            except Exception as e:
                if self.backend == "flag":
                    sys.exit(f"❌ 强制 --backend flag 但 FlagEmbedding 不可用: {e}")
                print(f"⚠️  FlagEmbedding 不可用 ({e})，降级到 Ollama")

        # Ollama 降级
        try:
            import ollama
            print(f"🚀 尝试 Ollama bge-m3 ...")
            models = [m.model for m in ollama.list().models]
            if "bge-m3" not in models and "bge-m3:latest" not in models:
                sys.exit(
                    "❌ Ollama 未拉取 bge-m3 模型。\n"
                    "   请执行: ollama pull bge-m3\n"
                    "   或改用 FlagEmbedding: pip install FlagEmbedding"
                )
            self.backend = "ollama"
            print(f"   ✅ Ollama 后端就绪 (dense only)")
        except Exception as e:
            sys.exit(f"❌ Ollama 不可用: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """批量编码 → dense 向量列表 (1024-dim)"""
        if not texts:
            return []

        if self.backend == "flag":
            # FlagEmbedding 内置 batch
            output = self._flag_model.encode(
                texts,
                batch_size=self.batch_size,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense_vecs = output.get("dense_vecs", [])
            result = []
            for v in dense_vecs:
                result.append(v.tolist() if hasattr(v, "tolist") else list(v))
            return result

        # Ollama: 逐条 (可加并发，但 Ollama 内部已 batch)
        import ollama
        result = []
        for text in texts:
            # bge-m3 Ollama 输出 1024-dim
            r = ollama.embeddings(model=self._ollama_model, prompt=text[:8000])
            result.append(r["embedding"])
        return result

    def encode_full(self, texts: List[str]) -> List[Tuple[List[float], str, str]]:
        """
        批量编码 → 三向量 (仅 FlagEmbedding 后端)。

        Returns:
            List of (dense_list, sparse_lexicon_json, colbert_tokens_json)
            - dense_list: [float] * 1024
            - sparse_lexicon_json: JSON str of {bpe_token_id: weight}
            - colbert_tokens_json: JSON str of [[float]*1024, ...] (multi-vector)
        """
        if self.backend != "flag":
            raise RuntimeError("encode_full() 仅支持 flag 后端")
        if not texts:
            return []

        output = self._flag_model.encode(
            texts,
            batch_size=self.batch_size,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=True,
        )

        dense_vecs = output.get("dense_vecs", [])
        sparse_lexs = output.get("lexical_weights", [])
        colbert_vecs_list = output.get("colbert_vecs", [])

        results = []
        for i in range(len(texts)):
            # dense
            d = dense_vecs[i] if i < len(dense_vecs) else []
            dense = d.tolist() if hasattr(d, "tolist") else list(d)

            # sparse: {bpe_token_id_str: weight}
            s = sparse_lexs[i] if i < len(sparse_lexs) else {}
            sparse_json = json.dumps(
                {str(k): round(float(v), 6) for k, v in s.items()},
                ensure_ascii=False,
            )

            # colbert: multi-vector embeddings
            c = colbert_vecs_list[i] if i < len(colbert_vecs_list) else []
            if hasattr(c, "tolist"):
                colbert_json = json.dumps(c.tolist())
            elif isinstance(c, list):
                colbert_json = json.dumps(
                    [v.tolist() if hasattr(v, "tolist") else list(v) for v in c]
                )
            else:
                colbert_json = "[]"

            results.append((dense, sparse_json, colbert_json))

        return results


# ══════════════════════════════════════════════════════════════════
# 2. Collection 备份
# ══════════════════════════════════════════════════════════════════

def backup_collection(chroma_root: Path, collection_name: str, backup_root: Path) -> Path:
    """
    ChromaDB 单个 collection 没有独立文件夹，备份策略:
    把整个 chroma_root 在第一次备份时整目录复制一次（幂等，按 timestamp 命名）。
    后续同一轮重 embedding 的 collection 共用同一份备份。
    """
    backup_root.mkdir(parents=True, exist_ok=True)
    marker = backup_root / "_manifest.json"
    if marker.exists():
        with marker.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        if collection_name in manifest:
            return backup_root / manifest[collection_name]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_name = f"chroma_{ts}"
    dst = backup_root / dst_name
    print(f"   💾 整库备份 → {dst} (首次备份)")
    shutil.copytree(str(chroma_root), str(dst), ignore_dangling_symlinks=True)
    manifest_data = {}
    if marker.exists():
        with marker.open("r", encoding="utf-8") as f:
            manifest_data = json.load(f)
    manifest_data[collection_name] = dst_name
    with marker.open("w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)
    return dst


def backup_hub_db(db_path: Path, backup_root: Path) -> Path:
    """备份 hub_meta.db"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_root / f"hub_meta_{ts}.db"
    shutil.copy2(str(db_path), str(dst))
    print(f"   💾 hub_meta.db 备份 → {dst}")
    return dst


# ══════════════════════════════════════════════════════════════════
# 3. 核心重 embedding 逻辑
# ══════════════════════════════════════════════════════════════════

def reembed_collection(
    client,
    collection_name: str,
    encoder: BgeM3Encoder,
    batch_size: int = 64,
    dry_run: bool = False,
    metadata_only: bool = False,
) -> Dict[str, Any]:
    """
    对单个 collection 执行重 embedding，返回统计信息。

    metadata_only=True: 保留原 dense embedding 不动，只重写 sparse_lexicon / colbert_tokens。
    要求原 collection 已经有可用的 embeddings (比如已经是 bge-m3 1024-dim)。
    """
    stats = {
        "collection": collection_name,
        "total_docs": 0,
        "processed": 0,
        "failed": 0,
        "duration_sec": 0,
        "status": "pending",
        "mode": "metadata_only" if metadata_only else "full_reembed",
    }

    try:
        col = client.get_collection(name=collection_name)
    except Exception as e:
        stats["status"] = f"error: get_collection failed: {e}"
        return stats

    total = col.count()
    stats["total_docs"] = total
    print(f"   📚 {collection_name}: {total} 篇文档  (mode={stats['mode']})")

    if total == 0:
        stats["status"] = "skipped: empty"
        return stats

    if dry_run:
        stats["status"] = "dry-run: would re-embed"
        return stats

    # metadata_only 模式需要原 embeddings，先做 sanity check
    if metadata_only:
        sample = col.get(limit=1, include=["embeddings"])
        sample_embs = sample.get("embeddings")
        if sample_embs is None or len(sample_embs) == 0 or sample_embs[0] is None:
            sample_dim = 0
        else:
            sample_dim = len(sample_embs[0])
        if sample_dim == 0:
            stats["status"] = (
                "error: metadata_only 模式要求 collection 已有 embeddings，"
                "但当前 collection embeddings 为空。请改用完整 re-embed。"
            )
            print(f"      ❌ {stats['status']}")
            return stats
        print(f"      保留原 dense embedding (dim={sample_dim})，只补 hybrid metadata")

    t0 = time.time()
    offset = 0
    all_data = None
    while offset < total:
        if offset == 0:
            include = ["documents", "metadatas"]
            if metadata_only:
                include.append("embeddings")
            all_data = col.get(include=include)
            all_ids = all_data.get("ids", [])
            all_docs = all_data.get("documents", [])
            all_metas = all_data.get("metadatas", [])
            all_embs = all_data.get("embeddings") if metadata_only else None

        batch_ids = all_ids[offset:offset + batch_size]
        batch_docs = all_docs[offset:offset + batch_size]
        batch_metas = all_metas[offset:offset + batch_size]
        batch_embs = all_embs[offset:offset + batch_size] if all_embs is not None else None
        if not batch_ids:
            break

        # 过滤空文档
        if metadata_only:
            valid = [
                (i, d, m, e)
                for i, d, m, e in zip(batch_ids, batch_docs, batch_metas, batch_embs)
                if d and d.strip() and e is not None
            ]
            if not valid:
                offset += batch_size
                continue
            ids_v, docs_v, metas_v, embs_v = zip(*valid)
            ids_v, docs_v, metas_v, embs_v = list(ids_v), list(docs_v), list(metas_v), list(embs_v)
        else:
            valid = [
                (i, d, m)
                for i, d, m in zip(batch_ids, batch_docs, batch_metas)
                if d and d.strip()
            ]
            if not valid:
                offset += batch_size
                continue
            ids_v, docs_v, metas_v = zip(*valid)
            ids_v, docs_v, metas_v = list(ids_v), list(docs_v), list(metas_v)
            embs_v = None

        # 编码 dense + hybrid metadata
        full_triple = None
        if metadata_only:
            # 把 numpy 数组统一转成 Python list，避免 ChromaDB 序列化问题
            embeddings = [
                v.tolist() if hasattr(v, "tolist") else list(v) for v in embs_v
            ]
        elif encoder.backend == "flag":
            # flag 后端：一次编码出三向量 (dense + sparse + colbert)
            try:
                full_triple = encoder.encode_full(docs_v)
                embeddings = [triple[0] for triple in full_triple]
            except Exception as e:
                print(f"      ❌ encode_full failed at offset {offset}: {e}")
                stats["failed"] += len(ids_v)
                offset += batch_size
                continue
        else:
            # Ollama 后端：仅 dense
            try:
                embeddings = encoder.encode(docs_v)
            except Exception as e:
                print(f"      ❌ encode failed at offset {offset}: {e}")
                stats["failed"] += len(ids_v)
                offset += batch_size
                continue

        # 构建 hybrid metadata (覆盖旧的 sparse_lexicon / colbert_tokens)
        new_metas = []
        for idx, (doc, meta) in enumerate(zip(docs_v, metas_v)):
            meta = dict(meta or {})

            if full_triple is not None:
                # flag 后端三向量：用 native bge-m3 sparse/colbert 覆盖
                _, sparse_json, colbert_json = full_triple[idx]
                meta["sparse_lexicon"] = sparse_json
                meta["colbert_tokens"] = colbert_json
            else:
                # Ollama / metadata_only：用文本分词近似
                try:
                    hybrid = build_hybrid_metadata(doc)
                    meta.update(hybrid)
                except Exception as e:
                    meta["_hybrid_error"] = str(e)
            meta["_reembedded_at"] = datetime.now().isoformat(timespec="seconds")
            if metadata_only:
                # 保留原 embedding_model 标记 (因为它没变)
                meta.setdefault("_embedding_model_preserved", meta.get("_embedding_model", "unknown"))
            else:
                meta["_embedding_model"] = "bge-m3"
            new_metas.append(meta)

        # upsert 覆盖
        try:
            col.upsert(
                ids=ids_v,
                documents=docs_v,
                metadatas=new_metas,
                embeddings=embeddings,
            )
            stats["processed"] += len(ids_v)
        except Exception as e:
            print(f"      ❌ upsert failed at offset {offset}: {e}")
            stats["failed"] += len(ids_v)

        offset += batch_size

    stats["duration_sec"] = round(time.time() - t0, 2)
    stats["status"] = "ok" if stats["failed"] == 0 else f"partial: {stats['failed']} failed"
    return stats


# ══════════════════════════════════════════════════════════════════
# 4. hub_meta.db 更新
# ══════════════════════════════════════════════════════════════════

def update_hub_db_embedding_model(db_path: Path, collection_names: List[str]) -> int:
    """把 knowledge_base.embedding_model 改成 bge-m3"""
    hub_db = HubDB(str(db_path))
    hub_db.connect()
    updated = 0
    try:
        conn = hub_db.conn
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(collection_names))
        cur.execute(
            f"UPDATE knowledge_base SET embedding_model = ?, updated_at = ? "
            f"WHERE collection_name IN ({placeholders})",
            ["bge-m3", datetime.now().isoformat(timespec="seconds")] + list(collection_names),
        )
        updated = cur.rowcount
        conn.commit()
    finally:
        hub_db.close()
    return updated


# ══════════════════════════════════════════════════════════════════
# 5. 主流程
# ══════════════════════════════════════════════════════════════════

def discover_collections(client, only: Optional[List[str]] = None) -> List[str]:
    all_cols = [c.name for c in client.list_collections()]
    # 只处理 ako_ 开头的 (AKO 命名规范)
    ako_cols = [c for c in all_cols if c.startswith("ako_")]
    if only:
        ako_cols = [c for c in ako_cols if c in only]
    return sorted(ako_cols)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AKO Hub 全库重 embedding → bge-m3 + hybrid metadata"
    )
    ap.add_argument(
        "--hub-root", default=str(HUB_ROOT),
        help=f"AKO_Hub 根目录 (默认 {HUB_ROOT})。用于查找 config/hub.yaml 和默认路径。",
    )
    ap.add_argument(
        "--chroma-root", default=None,
        help="ChromaDB 根目录 (覆盖 hub.yaml / 默认 chroma_db)。"
             "百度云盘同步环境应传: 'E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/chroma_db'",
    )
    ap.add_argument(
        "--db-path", default=None,
        help="hub_meta.db 文件路径 (覆盖默认 <hub-root>/hub_meta.db)。"
             "百度云盘同步环境应传: 'E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/hub_meta.db'",
    )
    ap.add_argument(
        "--backup-dir", default=None,
        help="备份目录 (默认 <hub-root>/backups/reembed_<timestamp>/)",
    )
    ap.add_argument(
        "--collection", action="append", default=[],
        help="只处理指定 collection (可多次)。默认处理所有 ako_* collection",
    )
    ap.add_argument(
        "--backend", choices=["auto", "flag", "ollama"], default="auto",
        help="embedding 后端 (默认 auto = 先 Flag 后 Ollama)",
    )
    ap.add_argument(
        "--model-path", default="C:/Users/Yangyuehao/.cache/modelscope/BAAI/bge-m3",
        help="bge-m3 模型本地路径 (默认 ModelScope 缓存路径)。"
             "FlagEmbedding 后端使用，也可传 HuggingFace 模型名如 'BAAI/bge-m3'",
    )
    ap.add_argument("--batch-size", type=int, default=64, help="upsert 批大小")
    ap.add_argument("--encode-batch", type=int, default=16, help="FlagEmbedding 编码批大小")
    ap.add_argument("--dry-run", action="store_true", help="只扫描，不修改")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份 (不推荐)")
    ap.add_argument("--backup-only", action="store_true", help="只备份，不重 embedding")
    ap.add_argument(
        "--metadata-only", action="store_true",
        help="保留原 dense embedding 不动，只补 sparse_lexicon / colbert_tokens hybrid metadata。"
             "要求原 collection 已经使用 bge-m3 (1024-dim)。不需要加载 FlagEmbedding / Ollama，速度极快。",
    )
    ap.add_argument("--update-db", action="store_true", default=True,
                    help="更新 hub_meta.db 中 embedding_model 为 bge-m3 (默认开启)")
    ap.add_argument("--no-update-db", dest="update_db", action="store_false")
    args = ap.parse_args()

    hub_root = Path(args.hub_root).resolve()
    if not hub_root.exists():
        sys.exit(f"❌ hub-root 不存在: {hub_root}")

    # 解析路径 (沿用 KnowledgeHub 的默认约定，CLI 显式覆盖优先)
    db_path = Path(args.db_path).resolve() if args.db_path else hub_root / "hub_meta.db"
    chroma_root = Path(args.chroma_root).resolve() if args.chroma_root else hub_root / "chroma_db"
    if not chroma_root.exists():
        sys.exit(f"❌ 未找到 chroma_root: {chroma_root}")
    if args.update_db and not db_path.exists():
        sys.exit(
            f"❌ 未找到 hub_meta.db: {db_path}\n"
            f"   单机 AKO_knowledge 环境请加 --no-update-db 跳过元数据库更新"
        )

    # 备份目录
    if args.backup_dir:
        backup_dir = Path(args.backup_dir).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = hub_root / "backups" / f"reembed_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 70)
    print("AKO Hub 全库重 embedding")
    print("═" * 70)
    print(f"  hub-root   : {hub_root}")
    print(f"  db_path    : {db_path}")
    print(f"  chroma_root: {chroma_root}")
    print(f"  backup_dir : {backup_dir}")
    print(f"  backend    : {args.backend}")
    if not (args.dry_run or args.backup_only or args.metadata_only):
        print(f"  model-path : {args.model_path}")
    print(f"  dry-run    : {args.dry_run}")
    print(f"  mode       : {'metadata_only' if args.metadata_only else 'full_reembed'}")
    print()

    # 加载编码器 (dry-run / backup-only / metadata-only 时都不加载，省时间)
    encoder = None
    if not (args.dry_run or args.backup_only or args.metadata_only):
        encoder = BgeM3Encoder(
            backend=args.backend,
            batch_size=args.encode_batch,
            model_path=args.model_path,
        )
        print()

    # ChromaDB 客户端
    client = chromadb.PersistentClient(path=str(chroma_root))
    collections = discover_collections(client, only=args.collection or None)
    print(f"🔍 发现 {len(collections)} 个 AKO collection:")
    for c in collections:
        try:
            cnt = client.get_collection(name=c).count()
            print(f"   • {c}  ({cnt} docs)")
        except Exception as e:
            print(f"   • {c}  (⚠️  count failed: {e})")
    print()

    if not collections:
        print("没有需要处理的 collection，退出。")
        return 0

    # 备份
    if not args.no_backup:
        print("🔒 步骤 1/N: 备份")
        backup_hub_db(db_path, backup_dir)
        backup_collection(chroma_root, collections[0], backup_dir)
        print()
    if args.backup_only:
        print("✅ backup-only 模式完成。")
        return 0

    # 重 embedding
    all_stats: List[Dict[str, Any]] = []
    print("🚀 步骤 2/N: 重 embedding + hybrid metadata")
    for col_name in collections:
        print(f"\n▶ {col_name}")
        stats = reembed_collection(
            client=client,
            collection_name=col_name,
            encoder=encoder,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            metadata_only=args.metadata_only,
        )
        all_stats.append(stats)
        print(f"   ✓ status={stats['status']} "
              f"processed={stats['processed']}/{stats['total_docs']} "
              f"failed={stats['failed']} duration={stats['duration_sec']}s")

    # 更新 hub_meta.db (metadata_only 模式跳过：embedding_model 没变)
    if args.update_db and not args.dry_run and not args.metadata_only:
        print("\n📝 步骤 3/N: 更新 hub_meta.db.embedding_model → bge-m3")
        ok_cols = [s["collection"] for s in all_stats if s["status"] == "ok"]
        if ok_cols:
            n = update_hub_db_embedding_model(db_path, ok_cols)
            print(f"   ✓ 更新了 {n} 行 knowledge_base 记录")
        else:
            print("   ⚠️  没有成功处理的 collection，跳过")

    # 汇总
    print("\n" + "═" * 70)
    print("📊 汇总")
    print("═" * 70)
    total_docs = sum(s["total_docs"] for s in all_stats)
    total_proc = sum(s["processed"] for s in all_stats)
    total_fail = sum(s["failed"] for s in all_stats)
    print(f"  collections : {len(all_stats)}")
    print(f"  total docs  : {total_docs}")
    print(f"  processed   : {total_proc}")
    print(f"  failed      : {total_fail}")
    print(f"  backup      : {backup_dir}")

    # 写 JSON 报告
    report_path = backup_dir / "reembed_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "hub_root": str(hub_root),
            "backend": encoder.backend if encoder else "none",
            "dry_run": args.dry_run,
            "stats": all_stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"  report      : {report_path}")

    if total_fail > 0:
        print("\n⚠️  有失败文档，请检查 report 并考虑重跑")
        return 2
    print("\n✅ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
