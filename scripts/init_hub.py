"""
AKO Hub — 一键初始化脚本
init_hub.py: 初始化目录结构、元数据库、注册现有知识库。

用法：
    python scripts/init_hub.py --config config/hub.yaml
    python scripts/init_hub.py --sync-root "C:/Users/xxx/BaiduSyncdisk/AKO_Hub"

文档编号: AGE-TECH-AKO-HUB-001 §7.1
"""

import sys
import argparse
import yaml
from pathlib import Path

# 将项目根加入路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB
from core.knowledge_hub import KnowledgeHub
from core.file_bus import FileBus


# ── 目录结构模板（与 7 Agent + 1 Workflow 对齐） ─────────────────

DIR_TEMPLATE = [
    "chroma_db",
    "files/common",
    # 陶粒墙板项目
    "files/taoli_wallboard/tech_docs",
    "files/taoli_wallboard/drawings/qc_01",
    "files/taoli_wallboard/drawings/qc_02",
    "files/taoli_wallboard/drawings/qc_03",
    "files/taoli_wallboard/reports/analyzer_01",
    "files/taoli_wallboard/reports/analyzer_02",
    "files/taoli_wallboard/reports/analyzer_03",
    "files/taoli_wallboard/bp",
    "files/taoli_wallboard/workflow_outputs",
    # 样板房项目
    "files/sample_house/vibe_design",
    "files/sample_house/acceptance",
    "files/sample_house/audit",
    # 系统
    "files/system/logs",
    "files/system/backups",
    "docs/whitepapers",
]


# ── 现有知识库注册清单（与用户资产对齐） ─────────────────────────

INITIAL_KBS = [
    {
        "kb_id": "ako_knowledge_base",
        "kb_name": "AKO 通用知识库",
        "agent_name": "ALL",
        "project_tag": "common",
        "kb_type": "base",
        "description": "全员共享基础文档：规范、标准、通用材料库",
    },
    {
        "kb_id": "ako_tech_struct",
        "kb_name": "结构计算文档库",
        "agent_name": "AKO_architect_agent",
        "project_tag": "taoli",
        "kb_type": "struct",
        "description": "陶粒墙板结构计算书、荷载分析、节点详图",
    },
    {
        "kb_id": "ako_drawing_qc",
        "kb_name": "图纸质检库",
        "agent_name": "AKO_drawing_inspector",
        "project_tag": "taoli",
        "kb_type": "qc",
        "description": "图纸审查标准、历史错误案例、标注规范",
    },
    {
        "kb_id": "ako_image_corpus",
        "kb_name": "图像分析语料库",
        "agent_name": "AKO_image_analyzer",
        "project_tag": "taoli",
        "kb_type": "corpus",
        "description": "施工现场图像样本、缺陷标注、验收标准图",
    },
]


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_dirs(sync_root: Path) -> None:
    for rel in DIR_TEMPLATE:
        (sync_root / rel).mkdir(parents=True, exist_ok=True)
    print(f"[OK] 目录结构已创建: {sync_root}")


def init_database(db_path: Path, backup_dir: Path) -> None:
    hub = HubDB(db_path)
    hub.connect()
    hub.init_schema()
    hub.close()
    print(f"[OK] 元数据库已初始化: {db_path}")
    # 首次备份（空库）
    hub = HubDB(db_path)
    bkp = hub.backup(backup_dir)
    print(f"[OK] 首次备份: {bkp}")


def register_knowledge_bases(db_path: Path, chroma_root: Path) -> None:
    kh = KnowledgeHub(str(db_path), str(chroma_root))
    for kb in INITIAL_KBS:
        col_name = kh.register_kb(
            kb_id=kb["kb_id"],
            kb_name=kb["kb_name"],
            agent_name=kb["agent_name"],
            project_tag=kb["project_tag"],
            kb_type=kb["kb_type"],
            description=kb["description"],
        )
        print(f"[OK] 知识库注册: {kb['kb_id']} → Collection: {col_name}")


def main():
    parser = argparse.ArgumentParser(description="AKO Hub 一键初始化")
    parser.add_argument("--config", default="config/hub.yaml", help="配置文件路径")
    parser.add_argument("--sync-root", dest="sync_root", help="强制指定同步根目录（覆盖配置文件）")
    args = parser.parse_args()

    config_path = PROJECT_ROOT / args.config
    if not config_path.exists():
        print(f"[ERR] 配置文件不存在: {config_path}")
        sys.exit(1)

    cfg = load_config(str(config_path))
    sync_root = Path(args.sync_root) if args.sync_root else Path(cfg["sync_root"])
    sync_root = sync_root.resolve()

    # 创建目录
    create_dirs(sync_root)

    # 路径计算
    meta_db = sync_root / cfg.get("meta_db", "age_hub.db")
    chroma_root = sync_root / cfg.get("chroma_root", "chroma_db")
    file_root = sync_root / cfg.get("file_root", "files")
    backup_dir = sync_root / cfg.get("backup_dir", "system/backups")

    # 初始化数据库
    init_database(meta_db, backup_dir)

    # 注册知识库
    register_knowledge_bases(meta_db, chroma_root)

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[DONE] AKO Hub P0 基座初始化完成")
    print(f"  同步根目录: {sync_root}")
    print(f"  元数据库:   {meta_db}")
    print(f"  向量库:     {chroma_root}")
    print(f"  文件总线:   {file_root}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\n下一步：")
    print("  1. 修改现有 Agent 入口，生成文件后调用 FileBus.register()")
    print("  2. 运行测试: python tests/test_hub.py")
    print("  3. P1 阶段启动 Master Graph 搭建")


if __name__ == "__main__":
    main()
