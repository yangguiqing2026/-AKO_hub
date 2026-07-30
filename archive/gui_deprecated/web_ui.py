"""
AKO Hub — Web UI 控制面板
web_ui.py: 基于 Gradio 构建的交互式 Web 界面，提供任务管理、同步校验、系统监控和文件浏览功能。

启动方式：
    python web_ui.py

访问地址：
    http://127.0.0.1:7860

功能模块：
    1. 执行任务：提交 AI Agent 任务，实时查看执行结果
    2. 同步校验：检查项目文件同步状态，确保数据一致性
    3. 系统状态：查看任务统计、文件状态和知识库数量
    4. 文件列表：浏览和管理注册的文件资源

文档编号: AGE-TECH-AKO-HUB-002 §WebUI
"""

# [DEPRECATED_GUI] import gradio as gr
import json
from pathlib import Path
from typing import Dict, Any, List
import urllib.request
import concurrent.futures

# Hub 根目录（供适配器函数使用）
HUB_ROOT = Path(__file__).resolve().parent

# 导入 hub_api 接口
from hub_api import submit_task, sync_check, hub_status, list_files

# 导入注册表
from registry.workflows import list_spokes_by_type, SPOKE_REGISTRY


# ── 辅助函数：格式化 JSON 输出 ───────────────────────────────────

def format_json(data: Any) -> str:
    """将数据格式化为美观的 JSON 字符串。"""
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return f"格式化错误: {e}"


# ── 辅助函数：获取 Agent 列表 ───────────────────────────────────

def get_agent_choices() -> List[str]:
    """从注册表中获取所有已注册的 Agent 名称列表。"""
    agents = list_spokes_by_type("agent")
    return [agent["name"] for agent in agents if agent.get("status") == "registered"]


def get_workflow_choices() -> List[str]:
    """从注册表中获取所有已注册的工作流 ID 列表。"""
    workflows = list_spokes_by_type("workflow")
    return [wf["workflow_id"] for wf in workflows if wf.get("status") == "registered"]


# ── 健康检查 ──────────────────────────────────────────────────────

COMPONENTS = {
    "Hub API": "http://127.0.0.1:7862/health",
    "AKO Chat": "http://127.0.0.1:7861/health",
    "AKO Knowledge": "http://127.0.0.1:8000/health",
    "Image Analyzer": "http://127.0.0.1:8501/health",
}


def _poll_one(name: str, url: str, timeout: int = 2) -> dict:
    """Poll single component health endpoint."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return {"name": name, "status": data.get("status", "unknown"), "checks": data.get("checks", {}), "cache": data.get("cache")}
    except Exception as e:
        return {"name": name, "status": "down", "error": str(e)}


def check_components_health() -> str:
    """并发轮询所有组件 /health 端点，返回格式化报告。"""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_poll_one, n, u): n for n, u in COMPONENTS.items()}
            results = []
            for f in concurrent.futures.as_completed(futures, timeout=8):
                results.append(f.result())
    except concurrent.futures.TimeoutError:
        results = [{"name": n, "status": "timeout", "error": "健康检查总超时"} for n in COMPONENTS]
    except Exception as e:
        results = [{"name": n, "status": "error", "error": str(e)} for n in COMPONENTS]

    results.sort(key=lambda r: r["name"])

    lines = ["🫀 组件健康状态", "━━━━━━━━━━━━━━━━━━━━━━"]
    for r in results:
        icon = "✅" if r["status"] == "ok" else "❌"
        lines.append(f"  {icon} {r['name']}: {r['status']}")
        if r["status"] == "down":
            lines.append(f"     ↳ {r.get('error', '')}")
        elif r.get("checks"):
            for k, v in r["checks"].items():
                sub_icon = "✅" if v == "ok" or v.startswith("ok") else "⚠️"
                lines.append(f"     ↳ {sub_icon} {k}: {v}")
            # 缓存统计（仅Hub API返回）
            if r.get("cache"):
                c = r["cache"]
                lines.append(f"     ↳ 📦 缓存: {c.get('hits',0)}命中/{c.get('misses',0)}未命中 (命中率 {c.get('hit_rate',0):.1%})")

    lines.append(f"  ✅ Hub Gradio: ok (当前)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ── 标签页 1: 执行任务 ───────────────────────────────────────────

def execute_task(intent: str, project_tag: str, workflow_id: str = "", 
                 agent_name: str = "") -> str:
    """
    提交任务到 Master Graph 执行。
    
    Args:
        intent: 任务意图描述（必填）
        project_tag: 项目标签（必填）
        workflow_id: 可选的工作流 ID
        agent_name: 可选的 Agent 名称
    
    Returns:
        格式化后的 JSON 结果字符串
    """
    if not intent or not project_tag:
        return "❌ 错误：'任务意图' 和 '项目标签' 为必填项"
    
    # 构建 payload
    payload = {
        "intent": intent,
        "project_tag": project_tag,
    }
    if workflow_id:
        payload["workflow_id"] = workflow_id
    if agent_name:
        payload["agent_name"] = agent_name
    
    try:
        result = submit_task(payload)
        status_icon = "✅" if result.get("status") == "completed" else "⚠️" if result.get("status") == "failed" else "ℹ️"
        return f"{status_icon} 任务执行结果:\n\n{format_json(result)}"
    except Exception as e:
        return f"❌ 任务提交失败:\n\n{type(e).__name__}: {e}"


# ── 标签页 2: 同步校验 ───────────────────────────────────────────

def check_sync(project_tag: str, verbose: bool = False) -> str:
    """
    执行文件同步一致性校验。
    
    Args:
        project_tag: 项目标签（空则校验最近 100 个文件）
        verbose: 是否显示详细列表
    
    Returns:
        格式化后的 JSON 结果字符串
    """
    try:
        result = sync_check(project_tag=project_tag, verbose=verbose)
        
        # 提取关键信息作为摘要
        summary = result.get("sync_summary", "未知")
        sync_results = result.get("sync_results", {})
        total = sync_results.get("total", 0)
        synced = sync_results.get("synced", 0)
        conflicts = sync_results.get("conflicts", 0)
        
        header = f"📊 同步校验报告\n"
        header += f"━━━━━━━━━━━━━━━━━━━━━━\n"
        header += f"总文件数: {total}\n"
        header += f"已同步: {synced}\n"
        header += f"冲突: {conflicts}\n"
        header += f"状态: {summary}\n"
        header += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        return header + format_json(result)
    except Exception as e:
        return f"❌ 同步校验失败:\n\n{type(e).__name__}: {e}"


# ── 标签页 3: 系统状态 ───────────────────────────────────────────

def refresh_status() -> str:
    """
    刷新并显示 AKO Hub 全局状态 + 组件健康检查。
    """
    # 先做健康检查（容错：即使挂了也不影响页面加载）
    try:
        health_report = check_components_health()
    except Exception as e:
        health_report = f"⚠️ 健康检查异常: {e}"

    # Hub 数据状态
    try:
        result = hub_status()

        tasks = result.get("tasks", [])
        files = result.get("files", [])
        kbs = result.get("knowledge_bases", 0)

        hub_lines = [
            "",
            "📊 Hub 数据状态",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"知识库数量: {kbs}",
            "",
            "📋 任务统计:",
        ]
        for t in tasks:
            status = t.get("status", "unknown")
            count = t.get("count", 0)
            icon = "✅" if status == "completed" else "⏳" if status == "pending" else "❌" if status == "failed" else "ℹ️"
            hub_lines.append(f"  {icon} {status}: {count}")

        hub_lines.append(f"\n📁 文件统计:")
        for f in files:
            status = f.get("status", "unknown")
            count = f.get("count", 0)
            icon = "✅" if status == "synced" else "⚠️" if status == "conflict" else "ℹ️"
            hub_lines.append(f"  {icon} {status}: {count}")

        hub_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        hub_lines.append("")
        hub_lines.append(format_json(result))

        return health_report + "\n" + "\n".join(hub_lines)
    except Exception as e:
        return health_report + f"\n\n❌ Hub 数据获取失败:\n\n{type(e).__name__}: {e}"


# ── 标签页 4: 文件列表 ───────────────────────────────────────────

def fetch_files(project_tag: str = "", agent_name: str = "", 
                file_type: str = "", limit: int = 50) -> tuple:
    """
    获取并显示文件列表。
    
    Args:
        project_tag: 项目过滤
        agent_name: Agent 过滤
        file_type: 文件类型过滤
        limit: 最大返回数量
    
    Returns:
        (表格数据, 统计信息字符串)
    """
    try:
        files = list_files(
            project_tag=project_tag,
            agent_name=agent_name,
            file_type=file_type,
            limit=limit
        )
        
        if not files:
            return [], "ℹ️ 未找到符合条件的文件"
        
        # 构建表格数据
        table_data = []
        for f in files:
            # 确保 f 是字典类型
            if not isinstance(f, dict):
                continue
                
            table_data.append([
                str(f.get("file_id", "")),
                str(f.get("file_name", "")),
                str(f.get("project_tag", "")),
                str(f.get("agent_name", "")),
                str(f.get("file_type", "")),
                int(f.get("file_size", 0)) if f.get("file_size") is not None else 0,
                "✅" if f.get("is_synced") == 1 else "⚠️" if f.get("is_synced") == 2 else "❌",
                str(f.get("created_at", ""))[:19] if f.get("created_at") else ""
            ])
        
        # 统计信息
        synced_count = sum(1 for f in files if isinstance(f, dict) and f.get("is_synced") == 1)
        conflict_count = sum(1 for f in files if isinstance(f, dict) and f.get("is_synced") == 2)
        total_size = sum(int(f.get("file_size", 0)) if isinstance(f, dict) and f.get("file_size") is not None else 0 for f in files)
        
        stats = f"📊 共 {len(table_data)} 个文件 | "
        stats += f"✅ 已同步: {synced_count} | "
        stats += f"⚠️ 冲突: {conflict_count} | "
        stats += f"💾 总大小: {total_size / 1024:.2f} KB" if total_size > 0 else "💾 总大小: 0 KB"
        
        return table_data, stats
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return [], f"❌ 获取文件列表失败: {type(e).__name__}: {e}\n\n{error_detail}"


# ── 标签页 6: RAG 知识库对话 ──────────────────────────────────────

def rag_chat(question: str, kb_id: str = "all") -> str:
    """
    调用 AKO_chat 适配器进行 RAG 知识库问答。

    Args:
        question: 用户问题
        kb_id: 知识库 ID

    Returns:
        回答文本
    """
    if not question.strip():
        return "请输入问题"

    try:
        from agents.ako_chat_adapter import run as chat_run
        result = chat_run(
            question=question,
            kb_id=kb_id,
            project_tag="ECA",
        )
        if result.get("error"):
            return f"回答异常: {result['error']}"
        answer = result.get("summary", "无回答")
        # 尝试获取完整回答（summary 被截断了 200 字）
        output_files = result.get("output_files", [])
        if output_files:
            import json as _json
            try:
                data = _json.loads(Path(output_files[0]).read_text(encoding="utf-8"))
                answer = data.get("answer", answer)
                refs = data.get("references", [])
                if refs:
                    answer += "\n\n---\n引用来源:\n"
                    for r in refs[:5]:
                        answer += f"  [{r.get('index', '?')}] {r.get('source', '未知')}\n"
            except Exception:
                pass
        return answer
    except ImportError as e:
        return f"AKO_chat 适配器导入失败: {e}\n请确认 D:\\AKO_chat 依赖已安装"
    except Exception as e:
        return f"调用失败: {type(e).__name__}: {e}"


# ── 标签页 7: 图像分析 ─────────────────────────────────────────────

def analyze_image(image, intent: str = "图像分析") -> str:
    """
    调用 AKO_image_analyzer 适配器分析上传的图像。

    Args:
        image: Gradio 上传的图像（numpy array 或文件路径）
        intent: 分析意图

    Returns:
        分析结果文本
    """
    if image is None:
        return "请上传一张图像"

    # Gradio 上传的图像可能是 numpy array 或临时文件路径
    # 先保存为临时文件，再传给适配器
    import tempfile
    import numpy as np

    try:
        from PIL import Image as PILImage

        if isinstance(image, np.ndarray):
            img = PILImage.fromarray(image)
        elif isinstance(image, str) and Path(image).exists():
            # 已经是文件路径
            from agents.ako_image_analyzer import run as img_run
            result = img_run(
                intent=intent or "图像分析",
                project_tag="ECA",
                image_path=image,
                _hub_output_dir=str(HUB_ROOT / "files" / "ECA_wallboard" / "reports" / "analyzer"),
            )
            return _format_spoke_result(result)
        else:
            return "不支持的图像格式"

        # 保存临时文件
        tmp_dir = Path(tempfile.mkdtemp(prefix="ako_img_"))
        tmp_path = tmp_dir / "upload.png"
        img.save(str(tmp_path))

        from agents.ako_image_analyzer import run as img_run
        result = img_run(
            intent=intent or "图像分析",
            project_tag="ECA",
            image_path=str(tmp_path),
            _hub_output_dir=str(HUB_ROOT / "files" / "ECA_wallboard" / "reports" / "analyzer"),
        )
        return _format_spoke_result(result)

    except ImportError as e:
        return f"图像分析适配器导入失败: {e}"
    except Exception as e:
        return f"分析失败: {type(e).__name__}: {e}"


# ── 标签页 8: AKO 工作流 ──────────────────────────────────────────

def run_workflow(user_input: str, input_file=None) -> str:
    """
    调用 AKO工作流适配器执行完整工作流。

    Args:
        user_input: 文本输入
        input_file: 上传的文件（可选）

    Returns:
        工作流执行结果
    """
    if not user_input.strip() and input_file is None:
        return "请输入文本或上传文件"

    try:
        from agents.ako_workflow_adapter import run as wf_run

        kwargs = {
            "user_input": user_input,
            "project_tag": "ECA",
            "_hub_output_dir": str(HUB_ROOT / "files" / "ECA_wallboard" / "workflow_outputs"),
        }

        # 处理文件上传
        if input_file is not None:
            if hasattr(input_file, 'name'):
                kwargs["input_file"] = input_file.name
            elif isinstance(input_file, str):
                kwargs["input_file"] = input_file

        result = wf_run(**kwargs)
        return _format_spoke_result(result)

    except ImportError as e:
        return f"工作流适配器导入失败: {e}\n请确认 D:\\AKO工作流 依赖已安装"
    except Exception as e:
        return f"工作流执行失败: {type(e).__name__}: {e}"


def _format_spoke_result(result: dict) -> str:
    """格式化 Spoke 标准输出为可读文本。"""
    lines = []
    if result.get("error"):
        lines.append(f"错误: {result['error']}")
    if result.get("summary"):
        lines.append(f"结果: {result['summary']}")
    files = result.get("output_files", [])
    if files:
        lines.append(f"\n输出文件 ({len(files)} 个):")
        for f in files:
            lines.append(f"  - {f}")
    if not lines:
        lines.append("无输出")
    return "\n".join(lines)


# ── 构建 Gradio 界面 ─────────────────────────────────────────────

def create_interface():
    """创建并配置 Gradio 界面。"""
    
    # [DEPRECATED_GUI] with gr.Blocks(
        title="AKO Hub 控制面板",
    ) as app:
        
        # 页眉：Logo + 标题
        # [DEPRECATED_GUI] with gr.Row():
            # [DEPRECATED_GUI] with gr.Column(scale=1, min_width=80):
                gr.Image(
                    value=r"D:\AKO_Hub\ako_logo.png",
                    show_label=False,
                    container=False,
                    height=60,
                )
            # [DEPRECATED_GUI] with gr.Column(scale=4):
                # [DEPRECATED_GUI] gr.Markdown("# 阿格智造 AKO Hub 智能系统")
        # [DEPRECATED_GUI] gr.Markdown('<p class="subtitle">统一调度平台 · 任务管理 · RAG对话 · 图像分析 · 工作流 · 商业报价 · 内容营销 · 同步监控</p>')
        
        # 创建标签页
        # [DEPRECATED_GUI] with gr.Tabs():
            
            # ═══════════════════════════════════════════════════════
            # 标签页 1: 执行任务
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("🚀 执行任务", id="execute"):
                # [DEPRECATED_GUI] gr.Markdown("### 提交 AI Agent 任务到 Master Graph 执行")
                
                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] intent_input = gr.Textbox(
                            label="任务意图 *",
                            placeholder="例如：结构计算、荷载分析、构件设计...",
                            lines=3,
                            info="描述您希望 AI Agent 执行的任务"
                        )
                        # [DEPRECATED_GUI] project_input = gr.Textbox(
                            label="项目标签 *",
                            placeholder="例如：ECA、project_01...",
                            info="关联的项目标识符"
                        )
                        # [DEPRECATED_GUI] workflow_dropdown = gr.Dropdown(
                            label="工作流 ID（可选）",
                            choices=get_workflow_choices(),
                            value=None,
                            allow_custom_value=True,
                            info="从注册表选择或输入自定义工作流 ID"
                        )
                        # [DEPRECATED_GUI] agent_dropdown = gr.Dropdown(
                            label="Agent 名称（可选）",
                            choices=get_agent_choices(),
                            value=None,
                            allow_custom_value=True,
                            info="从注册表选择或输入自定义 Agent 名称"
                        )
                        
                        # [DEPRECATED_GUI] submit_btn = gr.Button("🚀 提交任务", variant="primary", size="lg")
                    
                    # [DEPRECATED_GUI] with gr.Column(scale=2):
                        # [DEPRECATED_GUI] result_output = gr.Textbox(
                            label="执行结果",
                            lines=20,
                            interactive=False
                        )
                
                # 示例 - 直接使用注册表中实际的 Agent 和工作流 ID
                gr.Examples(
                    examples=[
                        ["结构计算", "ECA", "AKO工作流", "AKO_architect_agent"],
                        ["图纸质检", "ECA", "AKO_drawing_inspector", "AKO_drawing_inspector"],
                        ["图像分析", "ECA", "AKO_image_analyzer", "AKO_image_analyzer"],
                        ["商业报价", "ECA", "", "AKO_business"],
                        ["装配式报价", "ECA", "", "AKO_quote"],
                        ["内容营销", "ECA", "", "AKO_media"],
                        ["多 Agent 协同", "ECA", "AKO工作流", "AKO_architect_agent"],
                    ],
                    inputs=[intent_input, project_input, workflow_dropdown, agent_dropdown],
                    label="快速示例（ECA 项目 - 已与实际注册的 Agent 对齐）"
                )
                
                submit_btn.click(
                    fn=execute_task,
                    inputs=[intent_input, project_input, workflow_dropdown, agent_dropdown],
                    outputs=result_output
                )
            
            # ═══════════════════════════════════════════════════════
            # 标签页 2: 同步校验
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("🔄 同步校验", id="sync"):
                # [DEPRECATED_GUI] gr.Markdown("### 检查项目文件同步状态，确保双机数据一致性")
                
                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] sync_project_input = gr.Textbox(
                            label="项目标签",
                            placeholder="留空则校验最近 100 个文件",
                            info="指定要校验的项目"
                        )
                        verbose_checkbox = gr.Checkbox(
                            label="显示详细列表",
                            value=False,
                            info="勾选后显示每个文件的详细同步状态"
                        )
                        # [DEPRECATED_GUI] sync_btn = gr.Button("🔍 开始校验", variant="primary", size="lg")
                    
                    # [DEPRECATED_GUI] with gr.Column(scale=2):
                        # [DEPRECATED_GUI] sync_output = gr.Textbox(
                            label="校验结果",
                            lines=20,
                            interactive=False
                        )
                
                sync_btn.click(
                    fn=check_sync,
                    inputs=[sync_project_input, verbose_checkbox],
                    outputs=sync_output
                )
            
            # ═══════════════════════════════════════════════════════
            # 标签页 3: 系统状态
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("📊 系统状态", id="status"):
                # [DEPRECATED_GUI] gr.Markdown("### 组件健康 + Hub 数据状态")
                
                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] refresh_btn = gr.Button("🔄 刷新状态", variant="primary", size="lg")
                
                # [DEPRECATED_GUI] status_output = gr.Textbox(
                    label="系统状态",
                    lines=35,
                    interactive=False
                )
                
                # 页面加载时自动刷新
                app.load(fn=refresh_status, inputs=None, outputs=status_output)
                refresh_btn.click(fn=refresh_status, inputs=None, outputs=status_output)
            
            # ═══════════════════════════════════════════════════════
            # 标签页 4: 文件列表
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("📁 文件列表", id="files"):
                # [DEPRECATED_GUI] gr.Markdown("### 浏览和管理注册的文件资源")
                
                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] file_project_input = gr.Textbox(
                            label="项目标签",
                            placeholder="留空显示全部",
                            info="按项目过滤"
                        )
                        # [DEPRECATED_GUI] file_agent_input = gr.Textbox(
                            label="Agent 名称",
                            placeholder="留空显示全部",
                            info="按 Agent 过滤"
                        )
                        # [DEPRECATED_GUI] file_type_input = gr.Textbox(
                            label="文件类型",
                            placeholder="例如：pdf、docx、xlsx",
                            info="按文件扩展名过滤"
                        )
                        limit_slider = gr.Slider(
                            minimum=10,
                            maximum=200,
                            value=50,
                            step=10,
                            label="显示数量"
                        )
                        # [DEPRECATED_GUI] fetch_btn = gr.Button("📥 获取列表", variant="primary", size="lg")
                    
                    # [DEPRECATED_GUI] with gr.Column(scale=3):
                        # [DEPRECATED_GUI] file_stats = gr.Markdown(label="统计信息")
                        file_table = gr.Dataframe(
                            headers=["ID", "文件名", "项目", "Agent", "类型", "大小(B)", "同步状态", "创建时间"],
                            datatype=["str", "str", "str", "str", "str", "number", "str", "str"],
                            interactive=False,
                            wrap=True,
                            column_widths=["100px", "200px", "100px", "100px", "80px", "100px", "100px", "150px"]
                        )
                
                fetch_btn.click(
                    fn=fetch_files,
                    inputs=[file_project_input, file_agent_input, file_type_input, limit_slider],
                    outputs=[file_table, file_stats]
                )
            
            # ═══════════════════════════════════════════════════════
            # 标签页 5: 管理 Agent
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("⚙️ 管理 Agent", id="manage"):
                # [DEPRECATED_GUI] gr.Markdown("### 查看和管理已注册的 Agent")
                
                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] gr.Markdown("#### 当前已注册的 Agent")
                        agent_list_display = gr.Dataframe(
                            headers=["名称", "类型", "工作流 ID", "状态", "描述"],
                            datatype=["str", "str", "str", "str", "str"],
                            interactive=False,
                            wrap=True,
                            column_widths=["200px", "100px", "150px", "100px", "300px"]
                        )
                        # [DEPRECATED_GUI] refresh_agents_btn = gr.Button("🔄 刷新列表", variant="secondary")
                    
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] gr.Markdown("#### 注册新 Agent")
                        # [DEPRECATED_GUI] new_agent_name = gr.Textbox(
                            label="Agent 名称 *",
                            placeholder="例如：新的结构分析 Agent",
                            info="Agent 的显示名称"
                        )
                        # [DEPRECATED_GUI] new_agent_workflow_id = gr.Textbox(
                            label="工作流 ID *",
                            placeholder="例如：wf_new_agent",
                            info="唯一的工作流标识符"
                        )
                        # [DEPRECATED_GUI] new_agent_module = gr.Textbox(
                            label="Python 模块路径 *",
                            placeholder="例如：agents.new_agent",
                            info="Agent 代码所在的 Python 模块"
                        )
                        # [DEPRECATED_GUI] new_agent_function = gr.Textbox(
                            label="入口函数",
                            placeholder="例如：run",
                            value="run",
                            info="Agent 的入口函数名（LangGraph 子图留空）"
                        )
                        # [DEPRECATED_GUI] new_agent_description = gr.Textbox(
                            label="描述",
                            placeholder="简要描述 Agent 的功能",
                            lines=2,
                            info="Agent 的功能说明"
                        )
                        # [DEPRECATED_GUI] new_agent_source_dir = gr.Textbox(
                            label="源码目录 *",
                            placeholder="例如：D:/AKO_business_agent",
                            info="Spoke 项目源码的绝对路径"
                        )
                        new_agent_invoke_mode = gr.Radio(
                            label="调用模式",
                            choices=["importlib", "subprocess"],
                            value="importlib",
                            info="importlib=直接导入模块；subprocess=独立进程调用"
                        )
                        # [DEPRECATED_GUI] register_agent_btn = gr.Button("➕ 注册 Agent", variant="primary")
                        # [DEPRECATED_GUI] register_result = gr.Textbox(
                            label="注册结果",
                            lines=3,
                            interactive=False
                        )
                
                # 刷新 Agent 列表
                def refresh_agent_list():
                    """从注册表加载所有 Agent 并显示。"""
                    try:
                        agents = list_spokes_by_type("agent")
                        data = []
                        for agent in agents:
                            data.append([
                                agent.get("name", ""),
                                agent.get("spoke_type", ""),
                                agent.get("workflow_id", ""),
                                agent.get("status", ""),
                                agent.get("description", "")
                            ])
                        return data
                    except Exception as e:
                        return [["错误", "", "", "", f"加载失败: {e}"]]
                
                # 注册新 Agent（提示用户手动添加到注册表）
                def register_new_agent(name, workflow_id, module, function, description, source_dir, invoke_mode):
                    """生成注册新 Agent 的代码片段。"""
                    if not name or not workflow_id or not module:
                        return "❌ 错误：Agent 名称、工作流 ID 和模块路径为必填项"
                    if not source_dir:
                        return "❌ 错误：源码目录为必填项"

                    code_snippet = f"""
# 请将以下代码添加到 registry/workflows.py 的 SPOKE_REGISTRY 列表中：

{{
    "workflow_id": "{workflow_id}",
    "name": "{name}",
    "spoke_type": "agent",
    "entry_module": "{module}",
    "entry_function": "{function or 'run'}",
    "required_kb_ids": ["ako_knowledge_base"],
    "output_dir": "taoli_wallboard/agents/{workflow_id}",
    "description": "{description or '自定义 Agent'}",
    "status": "registered",
    "source_dir": "{source_dir}",
    "invoke_mode": "{invoke_mode or 'importlib'}",
}},
"""
                    return f"✅ 请复制以下代码并添加到 registry/workflows.py：\n\n{code_snippet}"
                
                # 绑定事件
                refresh_agents_btn.click(
                    fn=refresh_agent_list,
                    inputs=None,
                    outputs=agent_list_display
                )
                
                register_agent_btn.click(
                    fn=register_new_agent,
                    inputs=[new_agent_name, new_agent_workflow_id, new_agent_module, 
                           new_agent_function, new_agent_description, new_agent_source_dir, new_agent_invoke_mode],
                    outputs=register_result
                )
                
                # 页面加载时自动刷新
                app.load(fn=refresh_agent_list, inputs=None, outputs=agent_list_display)
        
            # ═══════════════════════════════════════════════════════
            # 标签页 6: RAG 知识库对话
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("💬 RAG 对话", id="rag_chat"):
                # [DEPRECATED_GUI] gr.Markdown("### 基于知识库的专业问答（建筑规范、陶粒墙板知识）")

                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] rag_question = gr.Textbox(
                            label="你的问题",
                            placeholder="例如：陶粒墙板抗压强度的规范要求是什么？",
                            lines=3,
                        )
                        # [DEPRECATED_GUI] rag_kb_id = gr.Dropdown(
                            label="知识库",
                            choices=["all", "ako_taoli_general_arch", "ako_taoli_building_codes_arch"],
                            value="all",
                            info="选择知识库范围",
                        )
                        # [DEPRECATED_GUI] rag_btn = gr.Button("🔍 提问", variant="primary", size="lg")

                    # [DEPRECATED_GUI] with gr.Column(scale=2):
                        # [DEPRECATED_GUI] rag_answer = gr.Textbox(
                            label="回答",
                            lines=20,
                            interactive=False,
                        )

                gr.Examples(
                    examples=[
                        ["陶粒墙板的抗压强度规范要求是什么？"],
                        ["装配式建筑的设计流程是怎样的？"],
                        ["陶粒混凝土配合比优化有哪些关键参数？"],
                    ],
                    inputs=[rag_question],
                    label="示例问题",
                )

                rag_btn.click(
                    fn=rag_chat,
                    inputs=[rag_question, rag_kb_id],
                    outputs=rag_answer,
                )

            # ═══════════════════════════════════════════════════════
            # 标签页 7: 图像分析
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("🖼️ 图像分析", id="image_analysis"):
                # [DEPRECATED_GUI] gr.Markdown("### 上传建筑图像进行 AI 分析（材料、风格、缺陷识别）")

                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        img_upload = gr.Image(
                            label="上传图像",
                            type="numpy",
                            height=300,
                        )
                        # [DEPRECATED_GUI] img_intent = gr.Dropdown(
                            label="分析意图",
                            choices=["图像分析", "缺陷识别", "材料识别", "风格分析", "施工现场验收"],
                            value="图像分析",
                        )
                        # [DEPRECATED_GUI] img_btn = gr.Button("🔬 开始分析", variant="primary", size="lg")

                    # [DEPRECATED_GUI] with gr.Column(scale=2):
                        # [DEPRECATED_GUI] img_result = gr.Textbox(
                            label="分析结果",
                            lines=20,
                            interactive=False,
                        )

                img_btn.click(
                    fn=analyze_image,
                    inputs=[img_upload, img_intent],
                    outputs=img_result,
                )

            # ═══════════════════════════════════════════════════════
            # 标签页 8: AKO 工作流
            # ═══════════════════════════════════════════════════════
            # [DEPRECATED_GUI] with gr.TabItem("⚡ 工作流", id="workflow"):
                # [DEPRECATED_GUI] gr.Markdown("### 陶粒墙板智能工作流（配比优化 → 商业计划 → 可行性分析）")

                # [DEPRECATED_GUI] with gr.Row():
                    # [DEPRECATED_GUI] with gr.Column(scale=1):
                        # [DEPRECATED_GUI] wf_input = gr.Textbox(
                            label="输入描述",
                            placeholder="例如：当前陶粒墙板配比：水泥 280kg/m³，陶粒 650kg/m³...\n目标性能：抗压强度 ≥ 5.0 MPa...",
                            lines=6,
                        )
                        wf_file = gr.File(
                            label="或上传文件（.docx / .pdf / .txt）",
                            file_types=[".docx", ".pdf", ".txt", ".md", ".pptx"],
                        )
                        # [DEPRECATED_GUI] wf_btn = gr.Button("⚡ 执行工作流", variant="primary", size="lg")

                    # [DEPRECATED_GUI] with gr.Column(scale=2):
                        # [DEPRECATED_GUI] wf_result = gr.Textbox(
                            label="执行结果",
                            lines=25,
                            interactive=False,
                        )

                gr.Examples(
                    examples=[
                        ["当前陶粒墙板配比：水泥 280kg/m³，陶粒 650kg/m³，水 180kg/m³，粉煤灰 80kg/m³。\n目标性能：抗压强度 ≥ 5.0 MPa，干密度 ≤ 950 kg/m³，导热系数 ≤ 0.20 W/(m·K)。\n请优化配比并生成商业计划。"],
                    ],
                    inputs=[wf_input],
                    label="示例输入",
                )

                wf_btn.click(
                    fn=run_workflow,
                    inputs=[wf_input, wf_file],
                    outputs=wf_result,
                )

        # 页脚
        # [DEPRECATED_GUI] gr.Markdown("---")
        # [DEPRECATED_GUI] gr.Markdown(
            '<div style="text-align: center; color: #94a3b8; font-size: 0.875rem;">'
            'AKO Hub v1.0 · AKO内部使用 · 基于 LangGraph 构建'
            '</div>'
        )
    
    return app


# ── 主程序入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("🎯 AKO Hub Web UI 启动中...")
    print("=" * 60)
    print("📖 文档: README.md / WEB_UI_README.md")
    print("🔗 访问地址: http://127.0.0.1:7860")
    print("=" * 60)
    
    # 定义主题 - AKO 品牌配色
    theme = gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
    )
    
    app = create_interface()
    # [DEPRECATED_GUI] app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,  # 如需公共链接，请先下载 frpc 隧道客户端
        show_error=True,
        theme=theme,
        css="""
        .gradio-container {
            max-width: 1200px !important;
        }
        h1 {
            color: #1a3a6b !important;
            text-align: center;
            font-weight: 700;
        }
        .subtitle {
            text-align: center;
            color: #64748b;
            margin-bottom: 20px;
        }
        .header-row {
            align-items: center;
        }
        """
    )
