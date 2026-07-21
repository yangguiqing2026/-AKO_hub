"""
AKO Hub — 第二台机器初始化脚本
init_second_machine.py: 检测已由第一台机器同步过来的 age_hub.db，完成本机适配。

执行场景：
  - 第一台机器已运行 init_hub.py，age_hub.db 已通过百度云盘同步到本机。
  - 本机需要确认：目录完整、machine_id 正确、向量库路径可用。

用法：
    python scripts/init_second_machine.py --config config/hub.yaml
    python scripts/init_second_machine.py --machine-id machine_02

文档编号: AGE-TECH-AKO-HUB-001 §P3
"""

import sys
import argparse
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.hub_db import HubDB
from core.distributed_lock import DistributedLock


# ── 目录结构模板（与 init_hub.py 保持一致） ─────────────────────────

DIR_TEMPLATE = [
    "chroma_db",
    "files/common",
    "files/taoli_wallboard/tech_docs",
    "files/taoli_wallboard/drawings/qc_01",
    "files/taoli_wallboard/drawings/qc_02",
    "files/taoli_wallboard/drawings/qc_03",
    "files/taoli_wallboard/reports/analyzer_01",
    "files/taoli_wallboard/reports/analyzer_02",
    "files/taoli_wallboard/reports/analyzer_03",
    "files/taoli_wallboard/bp",
    "files/taoli_wallboard/workflow_outputs",
    "files/sample_house/vibe_design",
    "files/sample_house/acceptance",
    "files/sample_house/audit",
    "files/system/logs",
    "files/system/backups",
    "docs/whitepapers",
]


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_sync_root(sync_root: Path) -> dict:
    """检测同步根目录状态。"""
    status = {"exists": False, "has_db": False, "has_chroma": False, "missing_dirs": []}

    if not sync_root.exists():
        status["missing_dirs"].append(str(sync_root))
        return status

    status["exists"] = True

    db_file = sync_root / "age_hub.db"
    if db_file.exists():
        status["has_db"] = True
        size = db_file.stat().st_size
        status["db_size"] = size
    else:
        status["missing_dirs"].append("age_hub.db")

    chroma_dir = sync_root / "chroma_db"
    if chroma_dir.exists():
        status["has_chroma"] = True
    else:
        status["missing_dirs"].append("chroma_db")

    return status


def create_missing_dirs(sync_root: Path) -> None:
    """补建缺失目录。"""
    for rel in DIR_TEMPLATE:
        (sync_root / rel).mkdir(parents=True, exist_ok=True)
    print("[OK] 目录结构已补全")


def verify_database(db_path: Path) -> bool:
    """验证 age_hub.db 可连接且表存在。"""
    try:
        db = HubDB(db_path)
        db.connect()
        rows = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        db.close()
        tables = {r["name"] for r in rows}
        required = {"knowledge_base", "file_registry", "task_queue", "sync_log"}
        missing = required - tables
        if missing:
            print(f"[WARN] 数据库表缺失: {missing}")
            return False
        print("[OK] 数据库连接正常，表结构完整")
        return True
    except Exception as e:
        print(f"[ERR] 数据库验证失败: {e}")
        return False


def update_machine_id_in_config(config_path: Path, machine_id: str) -> None:
    """修改配置文件中的 machine_id。"""
    cfg = load_config(str(config_path))
    cfg["machine_id"] = machine_id
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
    print(f"[OK] 配置文件已更新 machine_id = {machine_id}")


def test_lock(db_path: str, machine_id: str) -> None:
    """测试分布式锁。"""
    lock = DistributedLock(str(db_path), machine_id)
    holder = lock.is_held()
    if holder is None:
        print("[OK] 当前无锁，本机可正常获取")
    elif holder == machine_id:
        print(f"[OK] 锁由本机持有: {holder}")
    else:
        print(f"[WARN] 锁由其他机器持有: {holder}")
        print("       本机当前为只读 standby，等待对方释放锁后可写入")


def main():
    parser = argparse.ArgumentParser(description="AKO Hub 第二台机器初始化")
    parser.add_argument("--config", default="config/hub.yaml", help="配置文件路径")
    parser.add_argument("--machine-id", default="machine_02", help="本机标识（默认 machine_02）")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / args.config

    if not config_path.exists():
        print(f"[ERR] 配置文件不存在: {config_path}")
        print("       请确保已复制 AKO_Hub 完整目录到本机")
        sys.exit(1)

    cfg = load_config(str(config_path))
    sync_root = Path(cfg.get("sync_root", "D:/BaiduSyncdisk/AKO_Hub")).resolve()
    machine_id = args.machine_id

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"[INIT] AKO Hub 第二台机器初始化")
    print(f"  同步根目录: {sync_root}")
    print(f"  本机标识:   {machine_id}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1. 检测同步状态
    status = check_sync_root(sync_root)
    if not status["exists"]:
        print(f"[ERR] 同步根目录不存在: {sync_root}")
        print("       请确认百度云盘已完成同步")
        sys.exit(1)

    if not status["has_db"]:
        print("[ERR] age_hub.db 尚未同步到本机")
        print("       请等待百度云盘同步完成，或检查同步目录设置")
        sys.exit(1)

    print(f"[OK] age_hub.db 已同步 ({status.get('db_size', 0)} bytes)")

    # 2. 补建目录
    create_missing_dirs(sync_root)

    # 3. 验证数据库
    db_path = sync_root / "age_hub.db"
    if not verify_database(db_path):
        print("[WARN] 数据库验证未完全通过，建议等待同步完成后再试")

    # 4. 更新配置
    update_machine_id_in_config(config_path, machine_id)

    # 5. 测试分布式锁
    test_lock(str(db_path), machine_id)

    # 6. 最终报告
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[DONE] 第二台机器初始化完成")
    print(f"  机器标识: {machine_id}")
    print(f"  运行方式: python master/runner.py status")
    print(f"  同步校验: python master/runner.py sync --project taoli")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\n注意事项：")
    print("  1. 本机 machine_id 已设为 machine_02，与第一台机器区分")
    print("  2. 若锁被其他机器持有，本机只能执行只读查询（status/list-files/sync）")
    print("  3. 写入操作（run）需等待对方释放锁或超时后自动释放")
    print("  4. 建议双机协商使用时间窗口，避免同时写入")


if __name__ == "__main__":
    main()
