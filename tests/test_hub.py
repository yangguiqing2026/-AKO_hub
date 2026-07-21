"""
AKO Hub — P0 测试脚本
test_hub.py: 验证元数据库、KnowledgeHub、FileBus 基础功能。

用法：
    python tests/test_hub.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hub_db import HubDB
from core.knowledge_hub import KnowledgeHub, make_collection_name
from core.file_bus import FileBus


def test_hub_db(tmp_path: Path) -> None:
    print("\n[TEST] HubDB 基础操作")
    db_path = tmp_path / "test_age_hub.db"
    hub = HubDB(db_path)
    hub.connect()
    hub.init_schema()

    # 插入一条知识库
    hub.execute(
        "INSERT INTO knowledge_base (kb_id, kb_name, agent_name, collection_name, vector_db_path) VALUES (?,?,?,?,?)",
        ("test_kb", "测试库", "test_agent", "ako_test_t_test", "/tmp/chroma"),
    )
    hub.commit()

    row = hub.fetchone("SELECT * FROM knowledge_base WHERE kb_id=?", ("test_kb",))
    assert row is not None
    assert row["kb_id"] == "test_kb"
    print("  [PASS] 建表 + 插入 + 查询")

    # 备份
    bkp_dir = tmp_path / "backups"
    bkp_path = hub.backup(bkp_dir)
    assert bkp_path.exists()
    print(f"  [PASS] 备份生成: {bkp_path.name}")

    hub.close()


def test_knowledge_hub(tmp_path: Path) -> None:
    print("\n[TEST] KnowledgeHub 命名与注册")
    db_path = tmp_path / "test_kh.db"
    chroma_root = tmp_path / "chroma"

    hub = KnowledgeHub(str(db_path), str(chroma_root))

    # 测试命名生成
    col = make_collection_name("taoli", "struct", "AKO_architect_agent")
    assert col == "ako_taoli_struct_arch"
    print(f"  [PASS] Collection 命名: {col}")

    # 注册
    col2 = hub.register_kb(
        kb_id="test_struct",
        kb_name="结构库",
        agent_name="AKO_architect_agent",
        project_tag="taoli",
        kb_type="struct",
    )
    assert col2 == "ako_taoli_struct_arch"
    print(f"  [PASS] 注册返回: {col2}")

    # 重复注册（幂等）
    col3 = hub.register_kb(
        kb_id="test_struct",
        kb_name="结构库",
        agent_name="AKO_architect_agent",
        project_tag="taoli",
        kb_type="struct",
    )
    assert col3 == col2
    print("  [PASS] 幂等注册")

    # 列表查询
    kbs = hub.list_kb_by_agent("AKO_architect_agent")
    assert len(kbs) >= 1
    print(f"  [PASS] 按 Agent 查询: {len(kbs)} 条")


def test_file_bus(tmp_path: Path) -> None:
    print("\n[TEST] FileBus 注册与检索")
    db_path = tmp_path / "test_fb.db"
    file_root = tmp_path / "files"
    file_root.mkdir()

    bus = FileBus(str(db_path), str(file_root))

    # 创建测试文件
    test_file = file_root / "taoli" / "test_doc.md"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("# 测试文档\n", encoding="utf-8")

    # 注册
    fid = bus.register(
        source_agent="AKO_architect_agent",
        source_node="generate_report",
        rel_path="taoli/test_doc.md",
        file_type="md",
        project_tag="taoli",
        version_tag="v0.1",
        descriptive_name="测试文档",
    )
    assert fid.startswith("ako_architect")
    print(f"  [PASS] 注册 file_id: {fid}")

    # 检索
    rows = bus.find_by_project("taoli")
    assert len(rows) == 1
    print(f"  [PASS] 按项目检索: {len(rows)} 条")

    # 校验
    result = bus.verify_sync(fid)
    assert result["status"] == "match"
    print(f"  [PASS] 本地校验: {result['status']}")

    # 生成文件名
    fname = bus.generate_filename("AKO_architect_agent", "结构计算书", "md")
    assert fname.startswith("v0.1_")
    assert "ako_architect" in fname
    print(f"  [PASS] 规范文件名: {fname}")


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_hub_db(tmp)
        test_knowledge_hub(tmp)
        test_file_bus(tmp)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[ALL PASS] P0 基座测试全部通过")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


if __name__ == "__main__":
    main()
