"""
AKO Hub — AKO_form_extractor 适配器
将 D:\AKO_form_extractor (表单数据提取) 包装为 Hub Spoke。
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

SOURCE_DIR = Path(r"D:\AKO_form_extractor")


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
    """Spoke 适配器入口。从 SFTP 拉取微信小程序表单数据。"""
    output_dir = Path(_hub_output_dir) if _hub_output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if str(SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(SOURCE_DIR))

    try:
        from scripts.extractor import FormExtractor

        extractor = FormExtractor()
        records = extractor.run()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 保存提取结果
        records_data = []
        for r in records:
            records_data.append({
                "form_id": getattr(r, "form_id", ""),
                "form_type": getattr(r, "form_type", ""),
                "data": getattr(r, "data", {}),
                "extracted_at": getattr(r, "extracted_at", ""),
            })

        result_file = output_dir / f"forms_{timestamp}.json"
        result_file.write_text(
            json.dumps(records_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = f"表单提取完成: {len(records)} 条新记录"

        return {
            "output_files": [str(result_file)],
            "summary": summary,
            "error": None,
        }

    except ImportError as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"AKO_form_extractor 导入失败: {e}。请确认 D:\\AKO_form_extractor 目录存在且依赖已安装。",
        }
    except Exception as e:
        return {
            "output_files": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    test_dir = Path("./tmp_ako_forms_outputs")
    ret = run(intent="提取表单", _hub_output_dir=str(test_dir))
    print(json.dumps(ret, ensure_ascii=False, indent=2))
