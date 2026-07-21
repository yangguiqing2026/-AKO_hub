#!/usr/bin/env python3
"""
AKO Hub 系统验证脚本
验证所有核心组件是否正常工作
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_imports():
    """测试所有模块导入"""
    print("测试模块导入...")
    
    modules_to_test = [
        ("core.hub_db", "HubDB"),
        ("core.file_bus", "FileBus"),
        ("core.knowledge_hub", "KnowledgeHub"),
        ("core.distributed_lock", "DistributedLock"),
        ("master.state", "MasterState"),
        ("master.nodes", "task_router"),
        ("master.graph", "get_master_graph"),
        ("registry.workflows", "get_spoke_by_id"),
        ("hub_api", "submit_task"),
    ]
    
    failed_imports = []
    
    for module_name, class_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)
            print(f"  ✓ {module_name}.{class_name}")
        except Exception as e:
            print(f"  ✗ {module_name}.{class_name}: {e}")
            failed_imports.append(f"{module_name}.{class_name}")
    
    return len(failed_imports) == 0, failed_imports

def test_config():
    """测试配置文件"""
    print("\n测试配置文件...")
    
    config_path = PROJECT_ROOT / "config" / "hub.yaml"
    if not config_path.exists():
        print(f"  ✗ 配置文件不存在: {config_path}")
        return False
    
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        
        required_keys = ["sync_root", "meta_db", "chroma_root", "file_root", "machine_id"]
        missing_keys = [key for key in required_keys if key not in cfg]
        
        if missing_keys:
            print(f"  ✗ 配置缺少键: {missing_keys}")
            return False
        
        print(f"  ✓ 配置文件完整")
        return True
    except Exception as e:
        print(f"  ✗ 配置文件读取失败: {e}")
        return False

def test_database_schema():
    """测试数据库模式"""
    print("\n测试数据库模式...")
    
    try:
        from core.hub_db import HubDB
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = HubDB(db_path)
            db.connect()
            db.init_schema()
            
            # 检查表是否存在
            tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
            table_names = {t["name"] for t in tables}
            
            required_tables = {"knowledge_base", "file_registry", "task_queue", "sync_log"}
            missing_tables = required_tables - table_names
            
            if missing_tables:
                print(f"  ✗ 缺少表: {missing_tables}")
                return False
            
            print(f"  ✓ 数据库模式完整")
            db.close()
            return True
    except Exception as e:
        print(f"  ✗ 数据库测试失败: {e}")
        return False

def main():
    print("AKO Hub 系统验证")
    print("=" * 50)
    
    all_passed = True
    
    # 测试导入
    imports_ok, failed_imports = test_imports()
    if not imports_ok:
        all_passed = False
        print(f"\n失败的导入: {', '.join(failed_imports)}")
    
    # 测试配置
    if not test_config():
        all_passed = False
    
    # 测试数据库模式
    if not test_database_schema():
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ 所有验证通过！系统准备就绪。")
        return 0
    else:
        print("✗ 部分验证失败，请检查上述错误。")
        return 1

if __name__ == "__main__":
    sys.exit(main())