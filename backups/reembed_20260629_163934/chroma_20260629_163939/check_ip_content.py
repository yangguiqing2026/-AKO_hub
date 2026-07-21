"""
检查数据库中关于IP的具体内容
"""
import chromadb
from config_loader import get_config

config = get_config()

client = chromadb.PersistentClient(path=config.db_path)
col = client.get_collection(config.collection_name)

# 获取所有包含"IP"的记录
results = col.get(
    where={"source": "南明区永乐乡房车露营的品牌打造和IP形象的确立(1).pptx"}
)

print("=" * 60)
print("检查IP相关内容")
print("=" * 60)

ip_found = False
for i, (doc_id, doc, meta) in enumerate(zip(results['ids'], results['documents'], results['metadatas'])):
    if 'IP' in doc or 'ip' in doc.lower():
        ip_found = True
        print(f"\n[{i+1}] 片段索引: {meta.get('chunk_index', 'N/A')}")
        print(f"     相关度: N/A (全文检索)")
        print("-" * 60)
        # 显示前后200字符
        start = max(0, doc.find('IP') - 100) if 'IP' in doc else max(0, doc.lower().find('ip') - 100)
        end = min(len(doc), start + 300)
        print(doc[start:end])
        print("...")

if not ip_found:
    print("\n❌ 未找到包含'IP'关键词的内容")
    print("\n💡 可能原因:")
    print("   1. IP相关内容在图片中(OCR未识别)")
    print("   2. IP相关内容被切分到其他片段")
    print("   3. 文档本身没有详细阐述IP设计")

print("\n" + "=" * 60)
