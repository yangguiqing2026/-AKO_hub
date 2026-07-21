import chromadb
import ollama
from config_loader import get_config

config = get_config()
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_collection(config.collection_name)

query = "贵州省装配式建筑评价标准编号是多少"
r = ollama.embeddings(model=config.embedding_model, prompt=query)
res = col.query(query_embeddings=[r['embedding']], n_results=15)

print("前15个检索结果:")
for i, (meta, dist, doc) in enumerate(zip(res['metadatas'][0], res['distances'][0], res['documents'][0])):
    source = meta['source']
    has_db = 'DB' in doc or '编号' in doc
    print(f"{i+1}. {source[:40]:40} dist={dist:.3f} {'[含DB]' if has_db else ''}")
    if has_db:
        # 显示包含DB的行
        for line in doc.split('\n'):
            if 'DB' in line or '编号' in line:
                print(f"   → {line.strip()[:80]}")
