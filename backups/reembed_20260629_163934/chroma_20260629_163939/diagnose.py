import chromadb
import ollama
from config_loader import get_config

config = get_config()
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_collection(config.collection_name)

def embed(text):
    return ollama.embeddings(model=config.embedding_model, prompt=text)['embedding']

def diagnose(q: str, n: int = 10):
    print(f"\n{'='*60}")
    print(f"诊断查询: {q}")
    print(f"{'='*60}")
    
    res = col.query(
        query_embeddings=[embed(q)],
        n_results=n,
        include=["documents", "metadatas", "distances"]
    )
    
    docs = res['documents'][0]
    metas = res['metadatas'][0]
    dists = res['distances'][0]
    
    if not docs:
        print("⚠️  未召回任何片段")
        return
    
    print(f"\n召回 {len(docs)} 条，相似度分布:")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        score = 1 - dist
        source = meta.get('source', '?')
        ctype = meta.get('type', '?')
        print(f"\n[{i}] {source} | type:{ctype} | score:{score:.4f}")
        # 打印前200字看内容相关性
        preview = doc[:200].replace('\n', ' ')
        print(f"    {preview}...")
        
        # 标红低质量（score < 0.7）
        if score < 0.7:
            print(f"    ⚠️  相似度低于0.7，建议过滤")

if __name__ == "__main__":
    diagnose("陶粒墙板荷载验算")
    diagnose("轻质陶粒混凝土强度等级")
    diagnose("配筋要求")