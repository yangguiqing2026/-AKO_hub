"""
AKO Hub — 知识库迁移脚本

将各 Spoke 分散的 ChromaDB 数据合并到 Hub 统一库。

数据源：
  1. D:/AKO_knowledge/           → 集合 ako_photos           → Hub: ako_taoli_general_arch
  2. D:/AKO_architect_agent/knowledge_base/vector_store/
     集合 architecture_knowledge  → Hub: ako_taoli_building_codes_arch

目标：
  Hub ChromaDB: E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/chroma_db

用法：
  python migrate_knowledge.py              # 预览模式（dry-run）
  python migrate_knowledge.py --execute    # 执行迁移
  python migrate_knowledge.py --verify     # 仅校验迁移结果

依赖: pip install chromadb
"""

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("[错误] chromadb 未安装。请执行: pip install chromadb")
    sys.exit(1)

# ── 配置 ────────────────────────────────────────────────────────────

# Hub 目标
HUB_CHROMA_ROOT = Path("E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/chroma_db")
HUB_BACKUP_DIR  = Path("E:/数据库_同步百度云盘/BaiduSyncdisk/AKO_Hub/system/backups")

# 数据源定义
SOURCES = [
    {
        "name": "AKO_knowledge",
        "chroma_path": Path("D:/AKO_knowledge"),
        "source_collection": "ako_photos",
        "target_collection": "ako_taoli_general_arch",
        "source_tag": "ako_knowledge",
        "description": "PDF/图片/文档知识库（陶粒墙板规范、建筑标准等）",
    },
    {
        "name": "AKO_architect_agent",
        "chroma_path": Path("D:/AKO_architect_agent/knowledge_base/vector_store"),
        "source_collection": "architecture_knowledge",
        "target_collection": "ako_taoli_building_codes_arch",
        "source_tag": "architect_agent",
        "description": "建筑师 Agent 本地知识库（消防规范、面积标准、建材等）",
    },
]

# 每批写入条数
BATCH_SIZE = 64

# ── 日志 ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("migrate_knowledge")

# ── 工具函数 ────────────────────────────────────────────────────────

def backup_hub_chroma() -> Optional[Path]:
    """
    备份 Hub ChromaDB 目录。
    返回备份路径，失败返回 None。
    """
    if not HUB_CHROMA_ROOT.exists():
        logger.info("Hub ChromaDB 不存在，无需备份（首次迁移）")
        return None

    HUB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = HUB_BACKUP_DIR / f"chroma_backup_{ts}"

    try:
        shutil.copytree(HUB_CHROMA_ROOT, backup_path)
        logger.info(f"✅ 备份完成: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"❌ 备份失败: {e}")
        return None


def open_source_collection(source: Dict) -> Optional[Any]:
    """打开源 ChromaDB 集合，只读。"""
    chroma_path = source["chroma_path"]
    coll_name = source["source_collection"]

    if not chroma_path.exists():
        logger.warning(f"[{source['name']}] ChromaDB 路径不存在: {chroma_path}")
        return None

    try:
        client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_collection(coll_name)
        count = collection.count()
        logger.info(f"[{source['name']}] 打开集合 '{coll_name}'，共 {count} 条记录")
        return collection
    except Exception as e:
        logger.warning(f"[{source['name']}] 打开集合失败: {e}")
        return None


def fetch_all_records(collection: Any, batch_size: int = BATCH_SIZE) -> List[Dict]:
    """
    分批从源集合读取全部记录。
    返回 [{id, document, metadata, embedding}, ...]
    """
    records = []
    total = collection.count()
    if total == 0:
        return records

    # ChromaDB 不支持分页，一次取出再分批处理
    try:
        result = collection.get(include=["documents", "metadatas", "embeddings"])
    except Exception:
        # 部分旧版 ChromaDB 不支持同时取 embeddings，降级
        result = collection.get(include=["documents", "metadatas"])

    ids = result.get("ids", [])
    docs = result.get("documents", [])
    metas = result.get("metadatas", [])
    embeddings = result.get("embeddings")

    for i, doc_id in enumerate(ids):
        record = {
            "id": doc_id,
            "document": docs[i] if i < len(docs) else "",
            "metadata": metas[i] if i < len(metas) else {},
            "embedding": embeddings[i] if embeddings and i < len(embeddings) else None,
        }
        records.append(record)

    return records


def migrate_batch(
    target_collection: Any,
    records: List[Dict],
    source_tag: str,
) -> Tuple[int, int]:
    """
    批量写入目标集合。
    返回 (成功数, 失败数)。
    """
    success = 0
    failed = 0

    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        ids = [r["id"] for r in batch]
        docs = [r["document"] for r in batch]
        metas = []
        embeddings = []
        has_embeddings = False

        for r in batch:
            meta = r.get("metadata") or {}
            # 注入来源标记
            meta["_migrated_from"] = source_tag
            meta["_migrated_at"] = datetime.now().isoformat()
            metas.append(meta)

            emb = r.get("embedding")
            if emb:
                has_embeddings = True
                embeddings.append(emb)
            else:
                embeddings.append(None)

        try:
            kwargs = {"ids": ids, "documents": docs, "metadatas": metas}
            # 仅当所有记录都有 embedding 时才传（ChromaDB 要求全部或全无）
            if has_embeddings and all(e is not None for e in embeddings):
                kwargs["embeddings"] = embeddings

            target_collection.add(**kwargs)
            success += len(batch)
        except Exception as e:
            logger.error(f"批量写入失败 (batch offset={start}): {e}")
            failed += len(batch)

    return success, failed


# ── 主流程 ──────────────────────────────────────────────────────────

def preview() -> None:
    """预览模式：列出将要迁移的数据源和记录数。"""
    print("\n" + "=" * 60)
    print("  AKO 知识库迁移 — 预览模式 (dry-run)")
    print("=" * 60)

    for source in SOURCES:
        coll = open_source_collection(source)
        if coll is None:
            print(f"\n[{source['name']}] ⚠️ 不可用")
            continue
        count = coll.count()
        print(f"\n[{source['name']}]")
        print(f"  描述:   {source['description']}")
        print(f"  源路径: {source['chroma_path']}")
        print(f"  源集合: {source['source_collection']} ({count} 条)")
        print(f"  → 目标: {source['target_collection']}")

    print(f"\n目标 ChromaDB: {HUB_CHROMA_ROOT}")
    print("\n执行迁移请使用: python migrate_knowledge.py --execute")
    print("=" * 60 + "\n")


def execute() -> None:
    """执行迁移。"""
    print("\n" + "=" * 60)
    print("  AKO 知识库迁移 — 执行模式")
    print("=" * 60)

    # 1. 备份
    logger.info("步骤 1/3: 备份 Hub ChromaDB...")
    backup_path = backup_hub_chroma()
    if HUB_CHROMA_ROOT.exists() and backup_path is None:
        logger.error("备份失败，中止迁移。请手动备份后重试。")
        sys.exit(1)

    # 2. 打开目标 ChromaDB
    logger.info("步骤 2/3: 初始化目标 ChromaDB...")
    HUB_CHROMA_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        target_client = chromadb.PersistentClient(
            path=str(HUB_CHROMA_ROOT),
            settings=Settings(anonymized_telemetry=False),
        )
    except Exception as e:
        logger.error(f"目标 ChromaDB 初始化失败: {e}")
        sys.exit(1)

    # 3. 逐个迁移
    logger.info("步骤 3/3: 迁移数据...")
    total_success = 0
    total_failed = 0
    results_summary = []

    for source in SOURCES:
        print(f"\n--- 迁移 [{source['name']}] ---")
        coll = open_source_collection(source)
        if coll is None:
            logger.warning(f"跳过 {source['name']}（源不可用）")
            results_summary.append((source["name"], 0, 0, "跳过（源不可用）"))
            continue

        records = fetch_all_records(coll)
        if not records:
            logger.info(f"[{source['name']}] 源集合为空，跳过")
            results_summary.append((source["name"], 0, 0, "源集合为空"))
            continue

        # 获取或创建目标集合
        try:
            target_coll = target_client.get_or_create_collection(
                name=source["target_collection"],
                metadata={"hnsw:space": "cosine", "description": source["description"]},
            )
        except Exception as e:
            logger.error(f"创建目标集合失败: {e}")
            results_summary.append((source["name"], 0, len(records), f"创建集合失败: {e}"))
            continue

        before_count = target_coll.count()
        logger.info(f"目标集合 '{source['target_collection']}' 已有 {before_count} 条")

        success, failed = migrate_batch(target_coll, records, source["source_tag"])
        after_count = target_coll.count()

        logger.info(
            f"[{source['name']}] 迁移完成: 成功 {success}, 失败 {failed}, "
            f"目标集合现有 {after_count} 条"
        )

        total_success += success
        total_failed += failed
        results_summary.append((source["name"], success, failed, "完成"))

    # 汇总
    print("\n" + "=" * 60)
    print("  迁移结果汇总")
    print("=" * 60)
    for name, ok, fail, note in results_summary:
        status = "✅" if fail == 0 and ok > 0 else ("⚠️" if fail > 0 else "⏭️")
        print(f"  {status} {name}: 成功 {ok}, 失败 {fail} — {note}")
    print(f"\n  总计: 成功 {total_success}, 失败 {total_failed}")
    print("=" * 60 + "\n")


def verify() -> None:
    """校验迁移结果：检查目标集合记录数和数据完整性。"""
    print("\n" + "=" * 60)
    print("  AKO 知识库迁移 — 校验模式")
    print("=" * 60)

    if not HUB_CHROMA_ROOT.exists():
        print("❌ 目标 ChromaDB 不存在，请先执行迁移。")
        sys.exit(1)

    target_client = chromadb.PersistentClient(
        path=str(HUB_CHROMA_ROOT),
        settings=Settings(anonymized_telemetry=False),
    )

    all_ok = True
    for source in SOURCES:
        target_name = source["target_collection"]
        print(f"\n--- 校验 [{source['name']}] → {target_name} ---")

        try:
            coll = target_client.get_collection(target_name)
        except Exception:
            print(f"  ❌ 集合 '{target_name}' 不存在")
            all_ok = False
            continue

        count = coll.count()
        print(f"  记录数: {count}")

        if count == 0:
            print(f"  ⚠️ 集合为空")
            all_ok = False
            continue

        # 抽样检查
        sample = coll.get(limit=min(5, count), include=["documents", "metadatas"])
        ok_count = 0
        for i, doc_id in enumerate(sample["ids"]):
            doc = sample["documents"][i] if sample["documents"] else ""
            meta = sample["metadatas"][i] if sample["metadatas"] else {}
            migrated_from = meta.get("_migrated_from", "")
            if doc and migrated_from:
                ok_count += 1

        if ok_count == len(sample["ids"]):
            print(f"  ✅ 抽样 {len(sample['ids'])} 条全部包含迁移标记和文档内容")
        else:
            print(f"  ⚠️ 抽样 {len(sample['ids'])} 条中有 {len(sample['ids']) - ok_count} 条缺少迁移标记或文档")
            all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("  ✅ 所有集合校验通过")
    else:
        print("  ⚠️ 部分集合存在问题，请检查上方日志")
    print("=" * 60 + "\n")


# ── 入口 ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AKO 知识库迁移工具")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--execute", action="store_true", help="执行迁移")
    group.add_argument("--verify", action="store_true", help="校验迁移结果")
    args = parser.parse_args()

    if args.execute:
        execute()
    elif args.verify:
        verify()
    else:
        preview()
