"""
简单测试查询的距离值
"""
import chromadb
import ollama
from config_loader import get_config

config = get_config()

print("=" * 60)
print("查询距离测试")
print("=" * 60)

client = chromadb.PersistentClient(path=config.db_path)
col = client.get_collection(config.collection_name)

# 生成一个测试嵌入
test_text = "房车露营"
print(f"\n测试查询: '{test_text}'")

try:
    # 使用 Ollama 生成嵌入
    response = ollama.embeddings(model=config.embedding_model, prompt=test_text)
    query_embedding = response["embedding"]
    print(f"嵌入维度: {len(query_embedding)}")
    
    # 执行查询
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=5
    )
    
    if results['distances'] and len(results['distances']) > 0:
        distances = results['distances'][0]
        
        print(f"\n📊 距离分析:")
        print(f"   最小距离: {min(distances):.6f}")
        print(f"   最大距离: {max(distances):.6f}")
        print(f"   平均距离: {sum(distances)/len(distances):.6f}")
        
        max_dist = max(distances)
        print(f"\n🔍 距离类型判断:")
        if max_dist <= 2.0:
            print(f"   ✅ 余弦相似度 (cosine)")
            print(f"   公式: score = 1 - (distance / 2)")
            print(f"   示例: dist={distances[0]:.3f} → score={1 - (distances[0]/2):.3f}")
        elif max_dist < 100:
            print(f"   ⚠️  内积 (ip)")
            print(f"   公式: score = 1 / (1 + distance)")
        else:
            print(f"   ❌ 欧氏距离 (l2)")
            print(f"   当前距离: {distances[0]:.1f}")
            print(f"   公式: score = 1 / (1 + distance)")
            print(f"   示例: dist={distances[0]:.1f} → score={1/(1+distances[0]):.3f}")
        
        print(f"\n💡 结论:")
        if max_dist > 2.0:
            print(f"   数据库使用的是非余弦度量!")
            print(f"   建议: 删除数据库重新入库,或修改 query.py 的距离计算公式")
        else:
            print(f"   距离计算正常")
            
except Exception as e:
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
