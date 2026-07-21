"""
AKO Hub — AKO_netwatch_agent 适配器
将 D:\AKO_netwatch_agent (网络监控) 包装为 Hub Spoke。

支持操作：
  - check: 执行一轮全量检查（HTTP/SSL/域名/ICP）
  - status: 返回当前配置状态
"""
import sys
import json
import io
from pathlib import Path
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_netwatch_agent")


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
    """Spoke 适配器入口。执行网络监控检查。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 推断 action
    if not action:
        if any(kw in intent for kw in ["检查", "监控", "检测"]):
            action = "check"
        else:
            action = "status"

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from dotenv import load_dotenv
        from main import load_config
        from logger import setup_logger, get_logger
        from notifier import Notifier
        from monitor_engine import MonitorEngine
        from ops_engine import OpsEngine

        # 加载配置
        load_dotenv(str(SOURCE_DIR / "secrets.env"))
        config = load_config()

        if action == "status":
            # 仅返回配置摘要
            targets = config.get("targets", [])
            domains = config.get("domains", [])
            status_data = {
                "targets_count": len(targets),
                "domains_count": len(domains),
                "monitor_interval": config.get("monitor", {}).get("interval_minutes", "N/A"),
                "sftp_host": config.get("sftp", {}).get("host", ""),
                "notification_enabled": bool(config.get("notification", {}).get("smtp_host")),
                "timestamp": datetime.now().isoformat(),
            }
            status_file = output_dir / f"netwatch_status_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            status_file.write_text(
                json.dumps(status_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "output_files": [str(status_file)],
                "summary": f"监控配置: {len(targets)} 个目标, {len(domains)} 个域名",
                "error": None,
            }

        # 执行一轮检查
        log_buf = io.StringIO()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with redirect_stdout(log_buf), redirect_stderr(log_buf):
            notifier = Notifier(config)
            monitor = MonitorEngine(config, notifier)
            ops = OpsEngine(config, notifier)

            results = {
                "http": [],
                "ssl": [],
                "domain": [],
                "icp": [],
                "local_net": None,
            }

            # HTTP 检查
            for target in config.get("targets", []):
                try:
                    r = monitor.http_monitor.check(target.get("url", ""))
                    results["http"].append({"url": target.get("url"), "status": r})
                except Exception as e:
                    results["http"].append({"url": target.get("url"), "error": str(e)})

            # SSL 检查
            for domain_info in config.get("domains", []):
                try:
                    r = monitor.ssl_monitor.check(domain_info.get("domain", ""))
                    results["ssl"].append({"domain": domain_info.get("domain"), "status": r})
                except Exception as e:
                    results["ssl"].append({"domain": domain_info.get("domain"), "error": str(e)})

            # 域名检查
            for domain_info in config.get("domains", []):
                try:
                    r = monitor.domain_monitor.check(domain_info.get("domain", ""))
                    results["domain"].append({"domain": domain_info.get("domain"), "status": r})
                except Exception as e:
                    results["domain"].append({"domain": domain_info.get("domain"), "error": str(e)})

            # ICP 检查
            for domain_info in config.get("domains", []):
                try:
                    r = monitor.icp_monitor.check(domain_info.get("domain", ""))
                    results["icp"].append({"domain": domain_info.get("domain"), "status": r})
                except Exception as e:
                    results["icp"].append({"domain": domain_info.get("domain"), "error": str(e)})

            # 备份检查
            try:
                ops.check_backups()
                results["backup_ok"] = True
            except Exception:
                results["backup_ok"] = False

        result_file = output_dir / f"netwatch_check_{timestamp}.json"
        result_file.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log_file = output_dir / f"netwatch_check_{timestamp}.log"
        log_file.write_text(log_buf.getvalue(), encoding="utf-8")

        total_checks = len(results["http"]) + len(results["ssl"]) + len(results["domain"]) + len(results["icp"])
        error_count = sum(
            1 for cat in ["http", "ssl", "domain", "icp"]
            for item in results[cat] if "error" in item
        )

        return {
            "output_files": [str(result_file), str(log_file)],
            "summary": f"监控检查完成: {total_checks} 项, {error_count} 异常",
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_netwatch 导入失败: {e}。请确认 D:\\AKO_netwatch_agent 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_netwatch_outputs")
    ret = run(intent="检查", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))
