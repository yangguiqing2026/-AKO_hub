"""
AKO Hub — AKO_law_agent 适配器
将 D:\AKO\AKO_law_agent 包装为 Hub Spoke。

支持操作：
  - review:     六维度合规审查（compliance_review + 审查纪要）
  - self_check: 法律自检（legal_self_check）
  - health:     法律库健康检查（LawVault 可访问性与文件数）

说明：
  适配器直连真实的 AKOLawAgent / LawVault 类，不再依赖不存在的
  LawVaultReader / review_all_files / review_document。
"""
import sys
import json
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO\AKO_law_agent")
SRC_DIR = SOURCE_DIR / "src"


def _load_law_vault():
    """以独立模块方式加载 LawVault，避免包名冲突。"""
    vault_file = SRC_DIR / "services" / "law_vault.py"
    spec = importlib.util.spec_from_file_location("ako_law_vault", str(vault_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    """Spoke 适配器入口。法律审查 / 自检 / 健康检查。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 推断 action
    if not action:
        if any(kw in intent for kw in ["审查", "review", "合规", "评分"]):
            action = "review"
        elif any(kw in intent for kw in ["自检", "self_check", "自查", "检查"]):
            action = "self_check"
        elif any(kw in intent for kw in ["健康", "状态", "health"]):
            action = "health"
        else:
            action = "review"

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from AKO_law_agent_core import AKOLawAgent  # noqa: E402
        from dataclasses import asdict  # noqa: E402

        config_path = kwargs.get("config_path") or str(
            SOURCE_DIR / "AKO_law_agent_config.yaml"
        )
        agent = AKOLawAgent(config_path)

        if action == "review":
            doc_path = kwargs.get("doc_path", "") or kwargs.get("draft_path", "")
            if not doc_path:
                return {
                    "output_files": [],
                    "summary": "",
                    "error": "review 需要 doc_path 参数（待审查法律草案文件路径）",
                }
            result = agent.compliance_review(doc_path)
            log_path = agent.generate_review_log(result, str(output_dir))
            return {
                "output_files": [log_path] if log_path else [],
                "summary": f"{result.status.value}，总分 {result.total_score:.1f}/100",
                "scorecard": result.to_dict(),
                "error": None,
            }

        if action == "self_check":
            report = agent.legal_self_check()
            data = asdict(report)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result_file = output_dir / f"law_self_check_{timestamp}.json"
            result_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "output_files": [str(result_file)],
                "summary": f"法律自检完成: {report.status}",
                "results": data,
                "error": None,
            }

        # health
        vault_mod = _load_law_vault()
        vault_path = kwargs.get("vault_path")
        vault = vault_mod.LawVault(vault_path)
        file_count = len(vault.laws)
        health_data = {
            "vault_path": str(vault.path),
            "file_count": file_count,
            "tag_count": len(vault.tags),
            "status": "healthy" if file_count > 0 else "empty",
            "timestamp": datetime.now().isoformat(),
        }
        health_file = output_dir / f"law_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        health_file.write_text(
            json.dumps(health_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "output_files": [str(health_file)],
            "summary": f"法律 Agent 健康: Vault 内 {file_count} 个文件",
            "error": None,
        }

    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    ret = run(intent="法律自检", _hub_output_dir="./tmp_ako_law_outputs")
    print(json.dumps(ret, ensure_ascii=False, indent=2))