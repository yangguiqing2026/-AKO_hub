"""
AKO Hub — HTTP 检索服务
hub_server.py: 基于 FastAPI 暴露知识库检索 REST API，供 AKO-Chat-RAG 等外部服务调用。

启动方式：
    python hub_server.py
    uvicorn hub_server:app --host 127.0.0.1 --port 7862

接口：
    GET  /api/health              — 健康检查
    GET  /api/knowledge/list      — 列出已注册知识库
    POST /api/knowledge/query     — 检索知识库

文档编号: AGE-TECH-AKO-HUB-001 §HTTP
"""

import sys
from pathlib import Path
from typing import Optional

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# [DEPRECATED_GUI] from fastapi import FastAPI, HTTPException
# [DEPRECATED_GUI] from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.knowledge_hub import KnowledgeHub
from core.hub_db import HubDB

# ── FastAPI 应用 ──────────────────────────────────────────────────

# [DEPRECATED_GUI] app = FastAPI(
    title="AKO Hub Knowledge API",
    description="知识库统一检索 REST API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 数据模型 ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    kb_id: str = Field(..., description="知识库 ID / Collection 名称")
    query_text: str = Field(..., min_length=1, max_length=2000, description="查询文本")
    n_results: int = Field(5, ge=1, le=50, description="返回文档数")
    retrieval_mode: Optional[str] = Field(None, description="检索模式: hybrid / dense_only / sparse_only")

class KnowledgeBaseInfo(BaseModel):
    kb_id: str
    kb_name: str
    agent_name: str
    collection_name: str
    description: str

# ── 懒加载 KnowledgeHub ───────────────────────────────────────────

_knowledge_hub: Optional[KnowledgeHub] = None
_paths: Optional[dict] = None

def _resolve_paths() -> dict:
    global _paths
    if _paths is None:
        # 优先使用本地路径（PROJECT_ROOT 下），避免 yaml 中 sync_root 指向不可达远程路径
        local_db = PROJECT_ROOT / "hub_meta.db"
        local_chroma = PROJECT_ROOT / "chroma_db"
        if local_db.exists():
            _paths = {
                "db_path": str(local_db),
                "chroma_root": str(local_chroma),
            }
        else:
            try:
                import yaml
                cfg_path = PROJECT_ROOT / "config" / "hub.yaml"
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                root = Path(cfg["sync_root"]).resolve()
                _paths = {
                    "db_path": str(root / cfg.get("meta_db", "age_hub.db")),
                    "chroma_root": str(root / cfg.get("chroma_root", "chroma_db")),
                }
            except Exception:
                _paths = {
                    "db_path": str(local_db),
                    "chroma_root": str(local_chroma),
                }
    return _paths

def _get_hub() -> KnowledgeHub:
    global _knowledge_hub
    if _knowledge_hub is None:
        paths = _resolve_paths()
        _knowledge_hub = KnowledgeHub(
            db_path=paths["db_path"],
            chroma_root=paths["chroma_root"],
        )
    return _knowledge_hub

# ── 路由 ──────────────────────────────────────────────────────────

# [DEPRECATED_GUI] @app.get("/api/cache/stats")
async def cache_stats():
    """LRU 缓存统计"""
    return _get_hub().cache_stats

# [DEPRECATED_GUI] @app.post("/api/cache/clear")
async def cache_clear():
    """清空所有缓存"""
    _get_hub().clear_cache()
    return {"status": "ok", "message": "cache cleared"}

# [DEPRECATED_GUI] @app.get("/api/health")
async def health():
    """健康检查"""
    paths = _resolve_paths()
    return {
        "status": "ok",
        "service": "AKO Hub Knowledge API",
        "db_path": paths["db_path"],
        "chroma_root": paths["chroma_root"],
    }


# [DEPRECATED_GUI] @app.get("/health")
async def health_v2():
    """Health check endpoint — returns component + status + checks"""
    checks = {}

    # ChromaDB heartbeat
    try:
        hub = _get_hub()
        client = hub._ensure_client()
        client.heartbeat()
        checks["chromadb"] = "connected"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    # Hub meta DB
    try:
        paths = _resolve_paths()
        with HubDB(paths["db_path"]) as db:
            db.fetchall("SELECT 1")
        checks["db"] = "connected"
    except Exception as e:
        checks["db"] = f"error: {e}"

    return {
        "status": "ok",
        "component": "hub_api",
        "checks": checks,
        "cache": _get_hub().cache_stats,
    }

# [DEPRECATED_GUI] @app.get("/api/knowledge/list", response_model=list[KnowledgeBaseInfo])
async def list_knowledge_bases():
    """列出所有已注册的知识库"""
    paths = _resolve_paths()
    try:
        with HubDB(paths["db_path"]) as db:
            rows = db.fetchall(
                "SELECT kb_id, kb_name, agent_name, collection_name, description "
                "FROM knowledge_base ORDER BY kb_id"
            )
        return [
            KnowledgeBaseInfo(
                kb_id=r["kb_id"],
                kb_name=r["kb_name"],
                agent_name=r["agent_name"],
                collection_name=r["collection_name"],
                description=r.get("description", "") or "",
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询知识库列表失败: {e}")

# [DEPRECATED_GUI] @app.post("/api/knowledge/query")
async def query_knowledge(req: QueryRequest):
    """
    检索知识库

    优先按 kb_id 查询 Hub 元数据库，若 kb_id 未注册则回退为直接按 collection_name 查询 ChromaDB。

    返回 ChromaDB 原生查询结果：
    {
        "ids": [["id1", ...]],
        "documents": [["doc1", ...]],
        "metadatas": [[{...}, ...]],
        "distances": [[0.1, ...]],
        "similarities": [[0.9, ...]],
        "retrieval_mode": "hybrid"
    }
    """
    hub = _get_hub()
    try:
        results = hub.query(
            kb_id=req.kb_id,
            query_text=req.query_text,
            n_results=req.n_results,
            retrieval_mode=req.retrieval_mode,
        )
        return results
    except ValueError:
        # kb_id 未在 Hub 元数据库中注册，回退为直接按 collection_name 查询 ChromaDB
        pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    # fallback：直接用 collection_name 查询 ChromaDB（兼容旧 KB_MAP 命名）
    try:
        client = hub._ensure_client()
        col = client.get_or_create_collection(name=req.kb_id)
        results = col.query(
            query_texts=[req.query_text],
            n_results=req.n_results,
        )
        # 统一输出格式
        results["similarities"] = hub._distances_to_similarities(results.get("distances"))
        results["final_scores"] = results["similarities"]
        results["retrieval_mode"] = "dense_only"
        results["kb_id"] = req.kb_id
        return results
    except ValueError:
        raise HTTPException(status_code=404, detail=f"知识库/Collection 未找到: {req.kb_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"直接 ChromaDB 查询失败: {e}")

# ── 入口 ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="AKO Hub Knowledge API Server")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址")
    parser.add_argument("--port", type=int, default=7862, help="绑定端口")
    args = parser.parse_args()

    print(f"🚀 AKO Hub Knowledge API 启动: http://{args.host}:{args.port}")
    print(f"   API 文档: http://{args.host}:{args.port}/docs")
    # [DEPRECATED_GUI] uvicorn.run(app, host=args.host, port=args.port, log_level="info")