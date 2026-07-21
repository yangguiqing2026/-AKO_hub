"""诊断大文件入库问题"""
import os
import sys
import fitz
import chromadb
from config_loader import get_config

config = get_config()
PDF_FOLDER = config.pdf_folder

print("=" * 60)
print("大文件入库诊断")
print("=" * 60)
print(f"PDF 文件夹: {PDF_FOLDER}")
print(f"文件夹存在: {os.path.exists(PDF_FOLDER)}")

# 列出所有 PDF
all_files = [(f, os.path.getsize(os.path.join(PDF_FOLDER, f))) 
             for f in os.listdir(PDF_FOLDER) if f.lower().endswith('.pdf')]
all_files.sort(key=lambda x: -x[1])

print(f"\n发现 {len(all_files)} 个 PDF 文件:")
for name, size in all_files:
    print(f"  {size/1024/1024:.1f} MB  {name}")

# 检查 ChromaDB 中已入库的文件
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_or_create_collection(
    name=config.collection_name,
    metadata={"hnsw:space": "cosine"}
)

print(f"\n集合 '{config.collection_name}' 总记录数: {col.count()}")

# 获取所有已入库的 source
all_data = col.get(include=['metadatas'])
sources = set()
if all_data['metadatas']:
    for meta in all_data['metadatas']:
        if meta and 'source' in meta:
            sources.add(meta['source'])

print(f"已入库的文件 ({len(sources)} 个):")
for s in sorted(sources):
    print(f"  - {s}")

# 检查哪些文件未入库
print(f"\n--- 未入库的文件 ---")
for name, size in all_files:
    if name not in sources:
        print(f"  ** 未入库: {name} ({size/1024/1024:.1f} MB)")
    else:
        print(f"  [已入库] {name} ({size/1024/1024:.1f} MB)")

# 尝试打开大文件
print(f"\n--- 测试打开大文件 ---")
for name, size in all_files:
    if size > 100 * 1024 * 1024:  # > 100MB
        fpath = os.path.join(PDF_FOLDER, name)
        print(f"尝试打开: {name} ({size/1024/1024:.1f} MB)")
        try:
            doc = fitz.open(fpath)
            page_count = len(doc)
            print(f"  成功! 页数: {page_count}")
            # 测试第一页
            if page_count > 0:
                text = doc[0].get_text()
                print(f"  第1页文字长度: {len(text)} 字符")
            doc.close()
        except Exception as e:
            print(f"  失败: {e}")

print("\n" + "=" * 60)
