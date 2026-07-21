"""
AKO_Hub 知识库 API 服务 - 基于 bge-m3 三向量混合检索
"""
import os
import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chromadb
from config_loader import get_config
from hybrid_retrieval import HybridRetriever

app = FastAPI()

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
COLLECTION_NAME = config.collection_name
EMBEDDING_MODEL = config.embedding_model

# ==================== Hub 双写配置 ====================
_hub_client: Optional[chromadb.PersistentClient] = None
_hub_collection = None
_hub_collection_name: str = ""
_hub_enabled: bool = False

# 从 config.json 读取 hub_integration 配置
_config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
try:
    with open(_config_file, "r", encoding="utf-8") as _f:
        _raw = json.load(_f)
    _hub_cfg = _raw.get("hub_integration", {})
    if _hub_cfg.get("enabled", False):
        _hub_chroma_root = _hub_cfg["hub_chroma_root"]
        _hub_collection_name = _raw["profiles"][_raw["active_profile"]].get(
            "hub_collection", "ako_taoli_general_arch"
        )
        _hub_client = chromadb.PersistentClient(path=_hub_chroma_root)
        _hub_collection = _hub_client.get_or_create_collection(
            _hub_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        _hub_enabled = True
        print(f"[Hub 双写]   已启用 => {_hub_chroma_root}/{_hub_collection_name}")
except Exception as _e:
    print(f"[Hub 双写]   初始化失败 (本地模式正常运行): {_e}")

# =================================================

client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(COLLECTION_NAME)

# 初始化混合检索器
retriever = HybridRetriever(
    collection=collection,
    embedding_model=EMBEDDING_MODEL,
)


# 请求模型定义
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class AddRequest(BaseModel):
    doc_id: str
    text: str


# 响应模型定义
class SearchResponse(BaseModel):
    results: List[str]
    distances: List[float]
    ids: List[str]
    scores: Optional[List[float]] = None


class AddResponse(BaseModel):
    status: str
    message: str = ""


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    """搜索相似文档 - 使用 bge-m3 三向量混合检索"""
    try:
        result = retriever.search(request.query, top_k=request.top_k)

        if not result["documents"][0]:
            return SearchResponse(results=[], distances=[], ids=[], scores=[])

        return SearchResponse(
            results=result["documents"][0],
            distances=result["distances"][0],
            ids=result["ids"][0],
            scores=result.get("scores", [[]])[0],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@app.post("/add", response_model=AddResponse)
def add(request: AddRequest):
    """添加新文档 (同时双写到 Hub 统一库)"""
    try:
        # 检查文档ID是否已存在
        existing = collection.get(ids=[request.doc_id])
        if existing["ids"]:
            raise HTTPException(status_code=409, detail=f"文档ID '{request.doc_id}' 已存在")

        # 生成嵌入
        import ollama
        embed = ollama.embeddings(model=EMBEDDING_MODEL, prompt=request.text)["embedding"]

        # 构建含 sparse lexicon 的 metadata
        from hybrid_retrieval import build_hybrid_metadata
        meta = build_hybrid_metadata(request.text)
        meta["source"] = "api"
        meta["timestamp"] = ""

        collection.add(
            ids=[request.doc_id],
            embeddings=[embed],
            documents=[request.text],
            metadatas=[meta],
        )

        # 双写到 Hub
        hub_msg = ""
        if _hub_enabled and _hub_collection is not None:
            try:
                _hub_collection.add(
                    ids=[request.doc_id],
                    embeddings=[embed],
                    documents=[request.text],
                    metadatas=[{
                        "source": "ako_knowledge",
                        "local_collection": COLLECTION_NAME,
                        **meta,
                    }],
                )
                hub_msg = f" (已同步到 Hub: {_hub_collection_name})"
            except Exception as hub_e:
                hub_msg = f" (Hub 同步失败: {hub_e})"

        return AddResponse(status="ok", message=f"文档添加成功{hub_msg}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


@app.get("/")
def health():
    """健康检查"""
    return {
        "status": "running",
        "engine": "bge-m3 hybrid (dense + sparse + colbert)",
    }


@app.get("/hub_status")
def hub_status():
    """Hub 双写状态"""
    if not _hub_enabled:
        return {"hub_enabled": False, "message": "Hub 双写未启用"}
    try:
        count = _hub_collection.count() if _hub_collection else 0
        return {
            "hub_enabled": True,
            "hub_collection": _hub_collection_name,
            "hub_record_count": count,
            "local_collection": COLLECTION_NAME,
            "local_count": collection.count(),
        }
    except Exception as e:
        return {"hub_enabled": True, "error": str(e)}