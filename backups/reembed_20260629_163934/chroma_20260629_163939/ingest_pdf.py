import chromadb
import ollama
import uuid
import os
import io
import sys
import datetime
import fitz
from PIL import Image
import pytesseract

# ==================== Tesseract OCR 配置 ====================
# Windows 系统需要指定 tesseract.exe 的路径
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# ============================================================

from config_loader import get_config

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
PDF_FOLDER = config.pdf_folder
COLLECTION_NAME = config.collection_name
CHUNK_SIZE = config.chunk_size
OVERLAP = config.overlap
BATCH_SIZE = config.batch_size
EMBEDDING_MODEL = config.embedding_model
OCR_LANGUAGES = config.ocr_languages
# =================================================

client = chromadb.PersistentClient(path=DB_PATH)
col = client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}
)

def check_dependencies():
    """检查所有依赖是否就绪"""
    errors = []
    
    # 检查 Ollama 服务
    try:
        ollama.list()
    except Exception as e:
        errors.append(f"Ollama 服务未运行: {e}")
    
    # 检查 Tesseract OCR
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        errors.append(f"Tesseract OCR 未安装或配置错误: {e}")
    
    # 检查 PDF 文件夹
    if not os.path.exists(PDF_FOLDER):
        errors.append(f"PDF 文件夹不存在: {PDF_FOLDER}")
    
    # 检查是否有 PDF 文件
    if os.path.exists(PDF_FOLDER):
        pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith('.pdf')]
        if not pdf_files:
            errors.append(f"PDF 文件夹中没有 PDF 文件: {PDF_FOLDER}")
    
    if errors:
        print("❌ 依赖检查失败:")
        for err in errors:
            print(f"  - {err}")
        return False
    
    print("✅ 依赖检查通过")
    return True

def embed_batch(texts: list) -> list:
    """批量生成嵌入向量,提高性能"""
    embeddings = []
    for text in texts:
        try:
            r = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text[:1500])
            embeddings.append(r["embedding"])
        except Exception as e:
            print(f"  [错误] 嵌入生成失败: {e}")
            embeddings.append(None)  # 用 None 占位
    return embeddings

def embed(text: str):
    """单个文本嵌入(保留兼容性)"""
    r = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text[:1500])
    return r["embedding"]

def chunk_text(text: str):
    if not text or len(text) < 50:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - OVERLAP
    return chunks

def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, lang=OCR_LANGUAGES)
        return text.strip()
    except Exception as e:
        return f"[OCR失败: {e}]"

def iter_pdf_blocks(pdf_path: str):
    """逐页生成 PDF 文本块，避免一次性加载整个文件"""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  [错误] 无法打开 PDF: {e}")
        return
    
    processed_xrefs = set()
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # 提取文字
            try:
                text = page.get_text()
                if text.strip():
                    yield f"[第{page_num+1}页 文字]\n{text.strip()}"
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页文字提取失败: {e}")
            
            # 提取图片并 OCR
            try:
                images = page.get_images(full=True)
                for img_index, img in enumerate(images, start=1):
                    xref = img[0]
                    if xref in processed_xrefs:
                        continue
                    processed_xrefs.add(xref)
                    
                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue
                        ocr_text = ocr_image(base_image["image"])
                        if ocr_text and len(ocr_text) > 10:
                            yield f"[第{page_num+1}页 图{img_index} OCR]\n{ocr_text}"
                    except Exception as e:
                        print(f"  [警告] 第{page_num+1}页图{img_index} OCR 失败: {e}")
                        continue
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页图片处理失败: {e}")
    finally:
        doc.close()


def extract_pdf(pdf_path: str) -> str:
    """提取 PDF 内容,包括文字和 OCR 图片"""
    return "\n\n".join(iter_pdf_blocks(pdf_path))


def _add_chunks_to_collection(chunks: list, source_name: str, start_index: int):
    ids = [str(uuid.uuid4()) for _ in chunks]
    embs = embed_batch(chunks)
    valid_data = []
    for emb, doc, id_, chunk_index in zip(embs, chunks, ids, range(start_index, start_index + len(chunks))):
        if emb is not None:
            valid_data.append((emb, doc, id_, chunk_index))
    if not valid_data:
        return 0
    valid_embs, valid_docs, valid_ids, valid_indexes = zip(*valid_data)
    col.add(
        embeddings=list(valid_embs),
        documents=list(valid_docs),
        ids=list(valid_ids),
        metadatas=[{
            "source": source_name,
            "type": "pdf",
            "chunk_index": idx,
            "timestamp": datetime.datetime.now().isoformat()
        } for idx in valid_indexes]
    )
    return len(valid_docs)


def ingest_pdf_file(pdf_path: str, source_name: str):
    """处理单个 PDF 文件并入库"""
    print(f"处理: {source_name} ...")
    
    # 检查是否已入库
    existing = col.get(where={"source": source_name})
    if existing["ids"]:
        print(f"  [跳过] 已存在 {len(existing['ids'])} 条记录")
        return 0
    
    total = 0
    chunk_index = 0
    batch = []
    for block in iter_pdf_blocks(pdf_path):
        if not block or len(block.strip()) < 20:
            continue
        chunks = chunk_text(block)
        if not chunks:
            continue
        for chunk in chunks:
            batch.append(chunk)
            if len(batch) >= BATCH_SIZE:
                total += _add_chunks_to_collection(batch, source_name, chunk_index)
                chunk_index += len(batch)
                batch = []
    if batch:
        total += _add_chunks_to_collection(batch, source_name, chunk_index)
        chunk_index += len(batch)
    
    if chunk_index == 0:
        print(f"  [跳过] 内容过少")
        return 0
    
    print(f"  已生成 {chunk_index} 段, 已入库 {total} 条记录")
    return total

def main():
    """主函数:处理 PDF 文件夹中的所有文件"""
    print("=" * 60)
    print("PDF 知识库入库工具")
    print("=" * 60)
    
    # 显示当前配置
    print(f"\n{config.get_profile_info()}")
    print("=" * 60)
    
    # 依赖检查
    if not check_dependencies():
        print("\n请先解决上述依赖问题")
        return
    
    pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"目录无PDF: {PDF_FOLDER}")
        return
    
    print(f"\n发现 {len(pdf_files)} 个PDF，开始处理...")
    print("=" * 60)
    
    total_chunks = 0
    success_count = 0
    skip_count = 0
    
    for fn in pdf_files:
        fp = os.path.join(PDF_FOLDER, fn)
        try:
            n = ingest_pdf_file(fp, fn)
            total_chunks += n
            if n > 0:
                success_count += 1
                print(f"[完成] {fn} → {n} 段\n")
            else:
                skip_count += 1
                print(f"[跳过] {fn}\n")
        except Exception as e:
            skip_count += 1
            print(f"[错误] {fn} 处理失败: {e}\n")
    
    print("=" * 60)
    print(f"全部完成!")
    print(f"  成功: {success_count} 个文件")
    print(f"  跳过: {skip_count} 个文件")
    print(f"  共入库 {total_chunks} 段")
    print("=" * 60)
    print("\n提示: 等待百度云盘同步完成，再去另一台查询")

if __name__ == "__main__":
    main()