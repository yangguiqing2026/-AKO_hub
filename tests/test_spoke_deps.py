"""
测试三个新 Spoke 源项目的 Python 依赖可导入性。
"""
import sys
from pathlib import Path

TEST_CASES = [
    {
        "name": "AKO_business",
        "source_dir": r"D:\AKO_business_agent",
        "imports": [
            ("storage", None),
            ("models", None),
            ("engines.doc_generator", "DocGenerator"),
            ("engines.cost_engine", "CostEngine"),
            ("engines.risk_engine", "RiskEngine"),
            ("cli.briefing", None),
        ],
    },
    {
        "name": "AKO_quote",
        "source_dir": r"D:\AKO_quote_agent\ako_quote_agent",
        "imports": [
            ("quote_engine", "calculate_quote"),
        ],
    },
    {
        "name": "AKO_media",
        "source_dir": r"D:\AKO_media_agent",
        "imports": [
            ("src.main", "AKOMediaAgent"),
        ],
    },
]

print("=" * 60)
print("源项目依赖可导入性测试")
print("=" * 60)

for case in TEST_CASES:
    name = case["name"]
    source_dir = case["source_dir"]
    print(f"\n── {name} ──")
    print(f"   源码目录: {source_dir}")

    if not Path(source_dir).exists():
        print(f"   ❌ 目录不存在")
        continue

    src = str(Path(source_dir).resolve())
    path_inserted = False
    if src not in sys.path:
        sys.path.insert(0, src)
        path_inserted = True

    all_ok = True
    for mod_path, attr in case["imports"]:
        try:
            mod = __import__(mod_path, fromlist=["*"] if attr else [])
            if attr:
                obj = getattr(mod, attr, None)
                if obj is None:
                    print(f"   ❌ {mod_path}.{attr} — 属性不存在")
                    all_ok = False
                else:
                    print(f"   ✅ {mod_path}.{attr}")
            else:
                print(f"   ✅ {mod_path}")
        except ImportError as e:
            print(f"   ❌ {mod_path} — {e}")
            all_ok = False

    if path_inserted:
        try:
            sys.path.remove(src)
        except Exception:
            pass

    print(f"   {'✅ 全部通过' if all_ok else '❌ 存在缺失依赖'}")


# ── 额外检查 python-docx（AKO_business 需要） ──
print(f"\n── 第三方包 ──")
for pkg in ["docx", "filelock", "flask"]:
    try:
        __import__(pkg)
        print(f"   ✅ {pkg}")
    except ImportError:
        print(f"   ❌ {pkg} 未安装")
