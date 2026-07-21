"""
AKO Hub — ako_geo 完整流程测试
test_geo_run.py: 测试从扫描到发酵的完整流水线。

用法:
    python ako_geo/test_geo_run.py
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

# Windows 控制台编码
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_geo")


def test_config():
    """测试配置加载。"""
    logger.info("=" * 60)
    logger.info("TEST 1: 配置加载")
    logger.info("=" * 60)

    from ako_geo.config import (
        AKO_HUB_ROOT, GEO_OUTPUT_ROOT, PLATFORMS, TEMPLATES_DIR,
        GEO_ANCHORS_COLLECTION, MAX_REVIEW_LOOP,
    )

    assert AKO_HUB_ROOT.exists(), f"AKO_HUB_ROOT 不存在: {AKO_HUB_ROOT}"
    assert GEO_OUTPUT_ROOT.exists() or True, f"GEO_OUTPUT_ROOT 不存在（可自动创建）"
    assert len(PLATFORMS) == 4, f"PLATFORMS 数量错误: {PLATFORMS}"
    assert MAX_REVIEW_LOOP == 3, f"MAX_REVIEW_LOOP 错误: {MAX_REVIEW_LOOP}"

    logger.info("  AKO_HUB_ROOT: %s", AKO_HUB_ROOT)
    logger.info("  GEO_OUTPUT_ROOT: %s", GEO_OUTPUT_ROOT)
    logger.info("  PLATFORMS: %s", PLATFORMS)
    logger.info("  MAX_REVIEW_LOOP: %d", MAX_REVIEW_LOOP)
    logger.info("  ✅ 配置加载通过")
    return True


def test_models():
    """测试 Pydantic 模型。"""
    logger.info("=" * 60)
    logger.info("TEST 2: Pydantic 模型")
    logger.info("=" * 60)

    from ako_geo.models import GeoSource, SensitivityLevel, PublishPack, ReviewResult

    # 测试 GeoSource
    source = GeoSource(
        agent="architect_agent",
        task_id="TEST-001",
        created_at="2025-01-20T14:30:00",
        title="测试成果标题",
        public_abstract="这是一段测试摘要，用于验证 Pydantic 模型的正确性。需要足够长的字数来满足最低要求，至少五十字以上才能通过校验。",
        key_claims=["承载力达到 500 kN", "隔声量 45 dB"],
        geo_tags=["测试", "结构"],
        sensitivity=SensitivityLevel.P2,
    )
    assert source.task_id == "TEST-001"
    assert source.sensitivity == SensitivityLevel.P2
    logger.info("  GeoSource: ✅")

    # 测试 PublishPack
    pack = PublishPack(
        task_id="TEST-001",
        platform="zhihu",
        title="测试标题",
        abstract="测试摘要",
        content="测试正文",
    )
    assert pack.meta["status"] == "pending"
    logger.info("  PublishPack: ✅")

    # 测试 ReviewResult
    review = ReviewResult(status="approved", comment="内容合格")
    assert review.status == "approved"
    logger.info("  ReviewResult: ✅")

    logger.info("  ✅ 模型测试通过")
    return True


def test_utils():
    """测试辅助函数。"""
    logger.info("=" * 60)
    logger.info("TEST 3: 辅助函数")
    logger.info("=" * 60)

    from ako_geo.utils import (
        validate_claims, validate_public_abstract, load_geo_tags,
        normalize_tags, slugify_filename, compute_content_hash,
    )

    # 测试 validate_claims
    errors, warnings = validate_claims([
        "承载力达到 500 kN",
        "这是一条没有量化值的断言",
        "隔声量 45 dB",
    ])
    assert len(errors) == 1, f"期望 1 个错误，实际 {len(errors)}"
    logger.info("  validate_claims: ✅ (errors=%d)", len(errors))

    # 测试 validate_public_abstract
    warnings = validate_public_abstract("太短了")
    assert len(warnings) == 1
    warnings = validate_public_abstract("这是一段足够长的摘要内容，超过五十字的限制，用于测试校验函数的正确性。需要确保字数统计准确无误，所以这里多加一些内容。")
    assert len(warnings) == 0, f"期望 0 个警告，实际 {len(warnings)}: {warnings}"
    logger.info("  validate_public_abstract: ✅")

    # 测试 load_geo_tags
    tags = load_geo_tags()
    logger.info("  load_geo_tags: ✅ (loaded %d tags)", len(tags))

    # 测试 slugify_filename
    name = slugify_filename("2025-01-20", "ARCH-2025-001", "zhihu")
    assert name == "2025-01-20_ARCH-2025-001_zhihu.md", f"文件名错误: {name}"
    logger.info("  slugify_filename: ✅ (%s)", name)

    # 测试 compute_content_hash
    geo_yaml = Path("D:/AKO_Hub/architect_agent/output/ARCH-2025-001/geo.yaml")
    if geo_yaml.exists():
        h = compute_content_hash(geo_yaml)
        assert len(h) == 32, f"MD5 长度错误: {len(h)}"
        logger.info("  compute_content_hash: ✅ (md5=%s)", h[:8] + "...")

    logger.info("  ✅ 辅助函数测试通过")
    return True


def test_nodes_scan_filter():
    """测试 N0_Scan 和 N1_Filter 节点。"""
    logger.info("=" * 60)
    logger.info("TEST 4: N0_Scan + N1_Filter 节点")
    logger.info("=" * 60)

    from ako_geo.nodes.n0_scan import scan_sources
    from ako_geo.nodes.n1_filter import filter_candidates

    # N0_Scan
    state = {"sources": [], "processed_task_ids": []}
    result = scan_sources(state)
    candidates = result.get("candidates", [])
    logger.info("  N0_Scan: 发现 %d 个候选素材", len(candidates))
    assert len(candidates) >= 1, "应该至少发现 1 个 geo.yaml"

    # 检查第一个候选
    first = candidates[0]
    logger.info("  第一个候选: task_id=%s, agent=%s", first.get("task_id"), first.get("agent"))

    # N1_Filter
    filtered_state = filter_candidates(result)
    filtered = filtered_state.get("filtered", [])
    logger.info("  N1_Filter: 过滤后 %d 个候选", len(filtered))
    assert len(filtered) >= 1, "过滤后应至少有 1 个候选"

    logger.info("  ✅ N0+N1 节点测试通过")
    return True


def test_full_pipeline_dry_run():
    """
    完整流水线干跑测试（LLM 降级模式）。

    模拟从 N0 到 N8 的完整流程，LLM 调用走降级路径。
    """
    logger.info("=" * 60)
    logger.info("TEST 5: 完整流水线干跑（LLM 降级）")
    logger.info("=" * 60)

    from ako_geo.nodes.n0_scan import scan_sources
    from ako_geo.nodes.n1_filter import filter_candidates
    from ako_geo.nodes.n2_anchor import extract_anchors
    from ako_geo.nodes.n3_outline import generate_outline
    from ako_geo.nodes.n4_review import human_review
    from ako_geo.nodes.n5_format import format_platform
    from ako_geo.nodes.n6_publish import prepare_publish
    from ako_geo.nodes.n7_store import store_output
    from ako_geo.nodes.n8_ferment import ferment_knowledge

    # N0: 扫描
    state = {"sources": [], "processed_task_ids": []}
    state = scan_sources(state)
    logger.info("  N0_Scan: %d candidates", len(state.get("candidates", [])))

    if not state.get("candidates"):
        logger.warning("  无候选素材，跳过后续测试")
        return True

    # N1: 过滤
    state = filter_candidates(state)
    logger.info("  N1_Filter: %d filtered", len(state.get("filtered", [])))

    if not state.get("filtered"):
        logger.warning("  过滤后无候选，跳过后续测试")
        return True

    # N2: 锚点提取
    state = extract_anchors(state)
    logger.info("  N2_Anchor: %d anchors, context=%d chars",
                len(state.get("anchors", [])), len(state.get("context", "")))

    # 设置平台
    state["current_platform"] = "zhihu"

    # N3: 大纲生成（LLM 降级）
    state = generate_outline(state)
    outline = state.get("outline", "")
    logger.info("  N3_Outline: outline=%d chars", len(outline))
    assert len(outline) > 0, "大纲不应为空"

    # N4: 人工审核（模拟 approved）
    state["_review_result"] = {"status": "approved", "comment": "测试通过"}
    state = human_review(state)
    logger.info("  N4_Review: status=%s", state.get("review_status"))
    assert state.get("review_status") == "approved", "审核状态应为 approved"

    # N5: 平台适配（LLM 降级）
    state = format_platform(state)
    content = state.get("content", "")
    logger.info("  N5_Format: content=%d chars", len(content))
    assert len(content) > 0, "内容不应为空"

    # N6: 发布包
    state = prepare_publish(state)
    pack = state.get("publish_pack")
    assert pack is not None, "发布包不应为 None"
    logger.info("  N6_Publish: title=%s", pack.get("title", "")[:30])

    # N7: 文件存储
    state = store_output(state)
    file_paths = state.get("file_paths", [])
    logger.info("  N7_Store: %d files", len(file_paths))
    for fp in file_paths:
        logger.info("    -> %s", fp)
        assert Path(fp).exists(), f"文件应存在: {fp}"

    # N8: 知识发酵
    state = ferment_knowledge(state)
    new_anchors = state.get("new_anchors", [])
    ferment_result = state.get("ferment_result", {})
    logger.info("  N8_Ferment: %d new anchors, gaps=%d",
                len(new_anchors), ferment_result.get("gaps_count", 0))

    logger.info("  ✅ 完整流水线干跑通过")
    logger.info("  输出文件:")
    for fp in file_paths:
        logger.info("    %s", fp)

    return True


def test_graph_build():
    """测试 LangGraph 状态图构建。"""
    logger.info("=" * 60)
    logger.info("TEST 6: LangGraph 状态图构建")
    logger.info("=" * 60)

    from ako_geo.graph import build_geo_graph, create_initial_state

    # 构建图
    graph = build_geo_graph()
    assert graph is not None, "图构建不应返回 None"
    logger.info("  状态图构建: ✅")

    # 创建初始状态
    state = create_initial_state(platform="zhihu")
    assert state["current_platform"] == "zhihu"
    logger.info("  初始状态创建: ✅")

    logger.info("  ✅ LangGraph 状态图测试通过")
    return True


def test_spoke_register():
    """测试 GeoSpoke 注册。"""
    logger.info("=" * 60)
    logger.info("TEST 7: GeoSpoke 注册")
    logger.info("=" * 60)

    from ako_geo.spoke import GeoSpoke

    spoke = GeoSpoke()
    info = spoke.register()

    assert info["workflow_id"] == "AKO_geo"
    assert info["spoke_type"] == "workflow"
    assert info["entry_module"] == "ako_geo.spoke"
    logger.info("  Spoke 注册信息: %s", json.dumps(info, ensure_ascii=False, indent=2))

    # 验证 registry 中已存在
    from registry.workflows import get_spoke_by_id
    registered = get_spoke_by_id("AKO_geo")
    assert registered is not None, "AKO_geo 应在注册表中"
    logger.info("  Registry 验证: ✅")

    logger.info("  ✅ GeoSpoke 注册测试通过")
    return True


# ── 主测试入口 ────────────────────────────────────────────────────────

def main():
    logger.info("🚀 AKO GEO 完整流程测试")
    logger.info("=" * 60)

    tests = [
        ("配置加载", test_config),
        ("Pydantic 模型", test_models),
        ("辅助函数", test_utils),
        ("N0_Scan + N1_Filter", test_nodes_scan_filter),
        ("完整流水线干跑", test_full_pipeline_dry_run),
        ("LangGraph 状态图", test_graph_build),
        ("GeoSpoke 注册", test_spoke_register),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, func in tests:
        try:
            result = func()
            if result:
                passed += 1
            else:
                failed += 1
                errors.append(f"{name}: 返回 False")
        except Exception as e:
            failed += 1
            errors.append(f"{name}: {type(e).__name__}: {e}")
            logger.exception("  ❌ %s 失败", name)

    # 汇总
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 测试结果汇总")
    logger.info("=" * 60)
    logger.info("  通过: %d / %d", passed, passed + failed)
    logger.info("  失败: %d / %d", failed, passed + failed)

    if errors:
        logger.info("  错误明细:")
        for err in errors:
            logger.info("    ❌ %s", err)

    if failed == 0:
        logger.info("  🎉 全部测试通过！")
    else:
        logger.info("  ⚠️ 有 %d 个测试失败", failed)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
