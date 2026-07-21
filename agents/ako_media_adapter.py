"""
AKO Hub — AKO_media 适配器
将 D:\AKO_media_agent (5层内容营销流水线) 包装为 Hub Spoke。
"""
import sys
import json
import io
from pathlib import Path
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_media_agent")

CONFIG_PATH = r"D:/AKO_media_agent/config/AKO_media_agent_config.yaml"


def run(
    intent: str = "",
    project_tag: str = "taoli",
    action: str = "",
    platform: str = "all",
    _hub_output_dir: str = "",
    _hub_db_path: str = "",
    _hub_chroma_root: str = "",
    _hub_file_root: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Spoke 适配器入口。根据 intent 分发到媒体流水线的不同阶段。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 从 intent 推断 action
    if not action:
        action_map = {
            "采集": "crawl", "爬取": "crawl",
            "分析": "analysis",
            "决策": "decision",
            "发布": "publish",
            "进化": "evolution", "学习": "evolution",
            "流水线": "pipeline", "全流程": "pipeline",
        }
        for kw, act in action_map.items():
            if kw in intent:
                action = act
                break
        if not action:
            action = "pipeline"

    # 平台映射
    if "抖音" in intent:
        platform = "douyin"
    elif "公众号" in intent or "微信" in intent:
        platform = "wechat"
    elif "小红书" in intent:
        platform = "xiaohongshu"

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from src.main import AKOMediaAgent

        # 初始化
        agent = AKOMediaAgent(config_path=CONFIG_PATH)
        agent.initialize()

        # 捕获日志输出
        log_buf = io.StringIO()
        with redirect_stdout(log_buf), redirect_stderr(log_buf):
            if action == "crawl":
                full = kwargs.get("full", False)
                agent.run_crawl(platform=platform, full=full)
            elif action == "analysis":
                agent.run_analysis()
            elif action == "decision":
                agent.run_decision()
            elif action == "publish":
                stage = kwargs.get("stage", "draft")
                agent.run_publish(platform=platform, stage=stage)
            elif action == "evolution":
                agent.run_evolution()
            else:  # pipeline
                agent.run_full_pipeline()

            status = agent.get_status()

        agent.shutdown()

        # 保存输出
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_data = {
            "action": action,
            "platform": platform,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        result_file = output_dir / f"media_{action}_{timestamp}.json"
        result_file.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log_file = output_dir / f"media_{action}_{timestamp}.log"
        log_file.write_text(log_buf.getvalue(), encoding="utf-8")

        summary = f"媒体流水线 [{action}] 完成"
        if action == "pipeline":
            summary += "（采集→分析→决策→发布→反馈→进化）"

        return {
            "output_files": [str(result_file), str(log_file)],
            "summary": summary,
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_media 导入失败: {e}。请确认 D:\\AKO_media_agent 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_media_outputs")
    ret = run(
        intent="分析",
        project_tag="taoli_test",
        _hub_output_dir=str(test_dir),
    )
    print(json.dumps(ret, ensure_ascii=False, indent=2))
