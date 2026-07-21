"""检查每个文件的入库记录数"""
import chromadb
from config_loader import get_config

config = get_config()
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_or_create_collection(
    name=config.collection_name,
    metadata={"hnsw:space": "cosine"}
)

all_data = col.get(include=['metadatas', 'documents'])

# 按 source 统计
from collections import defaultdict
source_stats = defaultdict(lambda: {"count": 0, "total_chars": 0, "types": set()})

if all_data['metadatas']:
    for meta, doc in zip(all_data['metadatas'], all_data['documents']):
        if meta and 'source' in meta:
            src = meta['source']
            source_stats[src]["count"] += 1
            source_stats[src]["total_chars"] += len(doc) if doc else 0
            if 'type' in meta:
                source_stats[src]["types"].add(meta['type'])

print(f"总记录数: {col.count()}")
print(f"\n{'文件名':<50} {'记录数':>6} {'总字符':>10} {'类型'}")
print("-" * 80)
for src in sorted(source_stats.keys()):
    stats = source_stats[src]
    types_str = ','.join(stats['types'])
    print(f"{src:<50} {stats['count']:>6} {stats['total_chars']:>10} {types_str}")
