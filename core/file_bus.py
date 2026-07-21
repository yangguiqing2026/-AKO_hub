"""
AKO Hub — 文件总线
FileBus: 统一文件注册、检索、命名规范与同步校验。

文档编号: AGE-TECH-AKO-HUB-001 §5
"""

import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.hub_db import HubDB


# ── 命名规范（强制） ─────────────────────────────────────────────
# {version_tag}_{YYYYMMDD}_{HHMMSS}_{source_agent}_{descriptive_name}.{ext}

VALID_FILE_TYPES = {"pdf", "docx", "xlsx", "md", "png", "jpg", "jpeg", "json", "txt", "csv"}
VALID_PROJECT_TAGS = {"taoli", "sample", "common", "system"}


def _sanitize_filename(name: str) -> str:
    """移除或替换文件路径中的非法字符。"""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name).strip("_")


def make_file_id(source_agent: str, descriptive_name: str, timestamp: Optional[datetime] = None) -> str:
    """生成 file_id: {agent_short}_{ts}_{name_hash}。"""
    ts = (timestamp or datetime.now()).strftime("%Y%m%d%H%M%S")
    short = source_agent.replace("AKO_", "ako_").lower()
    name_hash = hashlib.sha256(descriptive_name.encode()).hexdigest()[:8]
    return f"{short}_{ts}_{name_hash}"


class FileBus:
    """
    文件总线：所有 Agent 与 Workflow 的产出文件必须经此注册。

    约束：
    1. 文件必须落在 sync_root/files/ 下，按项目分子目录。
    2. 命名必须符合规范，由 FileBus 校验或自动生成。
    3. 注册时自动计算 SHA-256 与文件大小，写入 file_registry。
    """

    def __init__(self, db_path: str, root_dir: str):
        self.db = HubDB(db_path)
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        # 自动建表（幂等）
        self.db.connect()
        self.db.init_schema()
        self.db.close()

    # ── 目录管理 ───────────────────────────────────────────────────

    def ensure_dir(self, rel_path: str) -> Path:
        """确保相对目录存在，返回绝对路径。"""
        target = (self.root_dir / rel_path).resolve()
        # 安全校验：禁止跳出 root_dir
        if not str(target).startswith(str(self.root_dir)):
            raise ValueError(f"目录路径越界: {rel_path}")
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ── 文件注册（核心） ───────────────────────────────────────────

    def register(self, source_agent: str, source_node: Optional[str],
                 rel_path: str, file_type: str, project_tag: str,
                 version_tag: str = "v0.1", descriptive_name: str = "") -> str:
        """
        注册文件到元数据表。

        Args:
            source_agent: 如 "AKO_architect_agent"
            source_node: LangGraph 节点名，如 "generate_report"
            rel_path: 相对于 files/ 的相对路径，如 "taoli_wallboard/tech_docs/v0.1_xxx.md"
            file_type: 扩展名（不含点）
            project_tag: 项目标签
            version_tag: 版本
            descriptive_name: 可读描述（用于生成 file_id）

        Returns:
            file_id: 全局唯一标识
        """
        file_type = file_type.lower().strip(".")
        if file_type not in VALID_FILE_TYPES:
            raise ValueError(f"不支持的文件类型: {file_type}. 允许: {VALID_FILE_TYPES}")
        if project_tag not in VALID_PROJECT_TAGS:
            raise ValueError(f"不合法的项目标签: {project_tag}. 允许: {VALID_PROJECT_TAGS}")

        abs_path = (self.root_dir / rel_path).resolve()
        if not str(abs_path).startswith(str(self.root_dir)):
            raise ValueError(f"文件路径越界: {rel_path}")
        if not abs_path.exists():
            raise FileNotFoundError(f"文件尚未落盘: {abs_path}")

        # 计算 hash & size
        file_hash = self.compute_hash(str(abs_path))
        file_size = abs_path.stat().st_size

        # 生成 file_id
        desc = descriptive_name or abs_path.stem
        file_id = make_file_id(source_agent, desc)

        with self.db:
            # 幂等：若 file_id 已存在，先删除旧记录（覆盖场景）
            self.db.execute("DELETE FROM file_registry WHERE file_id=?", (file_id,))
            self.db.execute(
                """INSERT INTO file_registry
                   (file_id, source_agent, source_node, rel_path, abs_path,
                    file_type, project_tag, version_tag, file_hash, file_size, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (file_id, source_agent, source_node, rel_path, str(abs_path),
                 file_type, project_tag, version_tag, file_hash, file_size,
                 datetime.now().isoformat()),
            )
        return file_id

    def compute_hash(self, abs_path: str) -> str:
        """计算 SHA-256。"""
        h = hashlib.sha256()
        with open(abs_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ── 检索 ──────────────────────────────────────────────────────

    def find_by_project(self, project_tag: str,
                        file_type: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM file_registry WHERE project_tag=?"
        params: List[Any] = [project_tag]
        if file_type:
            sql += " AND file_type=?"
            params.append(file_type.lower().strip("."))
        sql += " ORDER BY created_at DESC"
        with self.db:
            return self.db.fetchall(sql, tuple(params))

    def find_by_agent(self, agent_name: str,
                      project_tag: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM file_registry WHERE source_agent=?"
        params: List[Any] = [agent_name]
        if project_tag:
            sql += " AND project_tag=?"
            params.append(project_tag)
        sql += " ORDER BY created_at DESC"
        with self.db:
            return self.db.fetchall(sql, tuple(params))

    def find_by_file_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self.db:
            return self.db.fetchone("SELECT * FROM file_registry WHERE file_id=?", (file_id,))

    # ── 同步校验（P1 基础实现，P2 完善） ────────────────────────────

    def verify_sync(self, file_id: str) -> Dict[str, Any]:
        """
        本地校验：比对当前文件哈希与注册表中的哈希是否一致。
        P2 阶段扩展为双机比对。
        """
        row = self.find_by_file_id(file_id)
        if not row:
            return {"file_id": file_id, "status": "missing_in_registry", "is_synced": False}

        abs_path = Path(row["abs_path"])
        if not abs_path.exists():
            return {"file_id": file_id, "status": "missing_on_disk", "is_synced": False}

        current_hash = self.compute_hash(str(abs_path))
        registered_hash = row["file_hash"]
        is_match = current_hash == registered_hash

        status = "match" if is_match else "mismatch"
        with self.db:
            self.db.execute(
                "UPDATE file_registry SET is_synced=?, sync_verified_at=? WHERE file_id=?",
                (1 if is_match else 2, datetime.now().isoformat(), file_id),
            )
        return {
            "file_id": file_id,
            "status": status,
            "registered_hash": registered_hash,
            "current_hash": current_hash,
            "is_synced": is_match,
            "file_size": abs_path.stat().st_size,
        }

    def verify_all_by_project(self, project_tag: str) -> List[Dict[str, Any]]:
        """批量校验某项目下全部文件。"""
        files = self.find_by_project(project_tag)
        return [self.verify_sync(f["file_id"]) for f in files]

    # ── 生成规范文件名（辅助） ─────────────────────────────────────

    def generate_filename(self, source_agent: str, descriptive_name: str,
                          file_type: str, version_tag: str = "v0.1",
                          timestamp: Optional[datetime] = None) -> str:
        """按白皮书规范生成文件名。"""
        ts = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
        short = source_agent.replace("AKO_", "ako_").lower()
        name = _sanitize_filename(descriptive_name)
        ext = file_type.lower().strip(".")
        return f"{version_tag}_{ts}_{short}_{name}.{ext}"
