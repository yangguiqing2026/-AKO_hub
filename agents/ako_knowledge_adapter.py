"""
AKO Hub — AKO_knowledge 适配器
将 D:\AKO_knowledge (知识库服务) 包装为 Hub Spoke。

支持操作：
  - search: 混合检索
  - health: 健康检查
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_knowledge")


def run(
    intent: str = "",
    project_tag: str = "taoli",
    action: str = "",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。知识库检索 / 健康检查。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 推断 action
    if not action:
        if any(kw in intent for kw in ["搜索", "检索", "查询", "search"]):
            action = "search"
        elif any(kw in intent for kw in ["健康", "状态", "health"]):
            action = "health"
        elif any(kw in intent for kw in ["启动", "服务", "server"]):
            action = "server"
        else:
            action = "health"

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from config_loader import get_config
        from hybrid_retrieval import HybridRetriever

        config = get_config()

        if action == "search":
            query = kwargs.get("query", intent.replace("搜索", "").replace("检索", "").strip())
            if not query:
                query = "AKO 陶粒墙板"
            top_k = kwargs.get("top_k", 5)

            retriever = HybridRetriever(config)
            results = retriever.search(query, top_k=top_k)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result_file = output_dir / f"kb_search_{timestamp}.json"
            result_file.write_text(
                json.dumps({
                    "query": query,
                    "top_k": top_k,
                    "results": results,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            doc_count = len(results.get("documents", [[]])[0]) if results.get("documents") else 0
            return {
                "output_files": [str(result_file)],
                "summary": f"知识库检索完成: \"{query}\" → {doc_count} 条结果",
                "error": None,
            }

        else:  # health
            import chromadb
            from pathlib import Path as _Path

            chroma_root = config.get("common_settings", {}).get("chroma_root", str(SOURCE_DIR))
            client = chromadb.PersistentClient(path=chroma_root)
            collections = client.list_collections()

            health_data = {
                "collections": [c.name for c in collections],
                "collection_count": len(collections),
                "chroma_root": chroma_root,
                "timestamp": datetime.now().isoformat(),
            }
            health_file = output_dir / f"kb_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            health_file.write_text(
                json.dumps(health_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            return {
                "output_files": [str(health_file)],
                "summary": f"知识库健康: {len(collections)} 个集合",
                "error": None,
            }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_knowledge 导入失败: {e}。请确认 D:\\AKO_knowledge 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_knowledge_outputs")
    ret = run(intent="健康检查", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))
