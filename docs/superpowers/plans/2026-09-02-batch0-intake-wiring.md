# 批 0：Intake 在途接线收尾 + 命名清扫 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把工作台在途的 AKO_hub_intake_agent 接线改动（未提交：适配器/路由/SPOKE_REGISTRY/工单 API/DB 迁移/HTTP 端点）补齐测试与 taxonomy/命名注册，通过全链路验收后一次性合规提交，达到方案 §八 AC-01~10。

**Architecture:** 在途代码已按方案 §五"接线五层注册链"实现（①agent 侧 spoke 在 D:\AKO\AKO_hub_intake_agent 已存在 ②hub 适配器 `agents/ako_intake_adapter.py` ③SPOKE_REGISTRY ④routing_rules ⑤命名层待补）。本批只动 hub 仓库：补测试、补 taxonomy/命名缺口、验证后提交。intake 为 L3（工单闭环），hub_api 新增 allocate/deliver/manual_review/get_wo_status 四函数 + HTTP 四端点。

**Tech Stack:** Python 3.11（hub 运行环境，见 `ako_env_continue.ps1`）、sqlite3、http.server（标准库）、pytest（hub `tests/` 已有 pytest 用例与 script 型连通测试并存）。

**Spec:** `D:\AKO\AKO_hub\docs\AKO_hub_agent_connect_plan_v1.0.0.md`（§五/§六 8 步/§八 AC-01~10/§九 名单清扫）

## Global Constraints

- **执行目录**：D:\AKO\AKO_hub；所有命令在该目录运行（路径用正斜杠）。
- **禁碰生产库**：任何测试不得使用真实 `hub_meta.db`/`age_hub.db`——统一 tempfile + monkeypatch `hub_api._resolve_paths`。
- **契约**：spoke 返回三字段 `{output_files, summary, error}`（`core/spoke_protocol.py`）；接线五层注册链一处不漏。
- **命名制式**：短名 = 去 `AKO_` 前缀、去 `_agent` 后缀；`AKO_hub_intake_agent` 中文名"任务大门"。
- **提交规范**：commit message 带 `[batch0][intake]` 与 AC 编号；不提交运行时噪音文件（`chroma_db/chroma.sqlite3`、`hub_meta.db.bak.20260902_162809`、`registry/http_registered_agents.json` 的时间戳 diff）。
- **既有测试保护**：`tests/test_hub_api_taxonomy.py::test_all_registered_workflows_classified` 要求 SPOKE_REGISTRY 全部 workflow_id 在 TAXONOMY 有 domain+function——TAXONOMY 缺 `AKO_hub_intake_agent`（2026-09-02 核实），本批必须补，否则该测试红。

---

### Task 1: TAXONOMY 补 intake 分类（红测试先行）

**Files:**
- Modify: `registry/taxonomy.py`（TAXONOMY 字典，追加一条）
- Test: `tests/test_hub_api_taxonomy.py`（既有测试即红测试，不改动）

**Interfaces:**
- Consumes: `registry/taxonomy.py` 内常量 `DOMAIN_INFRASTRUCTURE`、`FUNCTION_ORCHESTRATOR`（已核实存在，行 32/50）
- Produces: `TAXONOMY["AKO_hub_intake_agent"] = {"domain": ..., "function": ...}`——供 Task 2 提交前让既有分类测试转绿

- [ ] **Step 1: 确认红测试**

运行（此刻 intake 已在 SPOKE_REGISTRY、taxonomy 未补，预期 FAIL）：

```bash
python -m pytest tests/test_hub_api_taxonomy.py::test_all_registered_workflows_classified -x -q
```

预期：FAIL，missing 列表含 `AKO_hub_intake_agent`。

- [ ] **Step 2: 补 TAXONOMY 条目**

在 `registry/taxonomy.py` 的 TAXONOMY 字典中、与 `AKO_hub` 条目（"基础设施"注释块内）相邻追加：

```python
    "AKO_hub_intake_agent": {
        "domain": DOMAIN_INFRASTRUCTURE,
        "function": FUNCTION_ORCHESTRATOR,
    },
```

> 归类依据：intake 是工厂唯一大门、面向全体系的人机入口，属基础设施域；其主责（歧义消解→工单编号→投递）与 hub 编排同职能。若后续体系标准另行归类，走 taxonomy 修订并同步本文件注释。

- [ ] **Step 3: 转绿验证**

```bash
python -m pytest tests/test_hub_api_taxonomy.py -q
```

预期：3 个用例全部 PASS（含分类落库与非法分类两条既有用例）。

- [ ] **Step 4: Commit（本 Task 独立提交，便于回滚）**

```bash
git add registry/taxonomy.py
git commit -m "[batch0][intake] taxonomy 补 AKO_hub_intake_agent 分类（infrastructure/orchestrator）AC-02"
```

---

### Task 2: 适配器与注册层冒烟测试

**Files:**
- Create: `tests/test_intake_registration.py`
- Test: 新建测试文件（本任务代码）

**Interfaces:**
- Consumes: `registry.workflows.SPOKE_REGISTRY`、`get_spoke_by_id("AKO_hub_intake_agent")`；`config/routing_rules.yaml`；`agents.ako_intake_adapter`（模块路径，导入不得触发 intake 重依赖——适配器顶层只做 sys.path，spoke 延迟构造已核实）
- Produces: 三条断言（注册条目完整 / 路由关键词就位 / 适配器可导入且 run 可调用）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_intake_registration.py`：

```python
# -*- coding: utf-8 -*-
"""批0：intake 注册层冒烟——SPOKE_REGISTRY 条目、routing 关键词、适配器可导入。"""
import importlib
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from registry.workflows import get_spoke_by_id  # noqa: E402

RULES_PATH = PROJECT_ROOT / "config" / "routing_rules.yaml"
REQUIRED_KEYWORDS = {
    "帮我": "AKO_hub_intake_agent",
    "我要": "AKO_hub_intake_agent",
    "工单": "AKO_hub_intake_agent",
    "大门": "AKO_hub_intake_agent",
}


def _load_keyword_routes():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["keyword"]: r["agent_id"] for r in rules.get("keyword_routes", [])}


def test_spoke_registry_entry_complete():
    entry = get_spoke_by_id("AKO_hub_intake_agent")
    assert entry is not None, "AKO_hub_intake_agent 未注册到 SPOKE_REGISTRY"
    assert entry["entry_module"] == "agents.ako_intake_adapter"
    assert entry["entry_function"] == "run"
    assert entry["invoke_mode"] == "importlib"
    assert entry["status"] == "registered"
    assert entry["source_dir"].endswith("AKO_hub_intake_agent")


def test_routing_keywords_target_intake():
    routes = _load_keyword_routes()
    for kw, agent in REQUIRED_KEYWORDS.items():
        assert routes.get(kw) == agent, f"关键词 {kw} 未路由到 {agent}（实际 {routes.get(kw)}）"


def test_adapter_import_and_run_callable():
    mod = importlib.import_module("agents.ako_intake_adapter")
    assert callable(getattr(mod, "run", None))
    assert callable(getattr(mod, "get_intake_status", None))
```

- [ ] **Step 2: 运行验证失败**

```bash
python -m pytest tests/test_intake_registration.py -q
```

预期：1 条以上 FAIL（当前 taxonomy 未补时 registry 无碍——失败点在第一条 entry 断言或 import 失败皆可，以"红"为准）。

- [ ] **Step 3: 修正至转绿**

条目/关键词缺漏时补 `registry/workflows.py`（对齐既有 writer 条目格式）或 `config/routing_rules.yaml`（关键词四连已在在途 diff，勿重复加）。import 失败时检查 `agents/ako_intake_adapter.py` 的 `INTAKE_ROOT` 路径解析。

```bash
python -m pytest tests/test_intake_registration.py -q
```

预期：3 条 PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/test_intake_registration.py
git commit -m "[batch0][intake] 注册层冒烟测试：SPOKE_REGISTRY/路由关键词/适配器导入 AC-01/02/03/07"
```

---

### Task 3: hub_api 工单 API 单测（temp DB）

**Files:**
- Create: `tests/test_intake_wo_api.py`
- Test: 新建测试文件

**Interfaces:**
- Consumes: `hub_api.allocate_wo(draft_wo_number, module, action, trigger_agent=..., ttl_seconds=300)`、`hub_api.deliver_wo(wo_dict)`、`hub_api.manual_review_wo(wo_dict)`、`hub_api.get_wo_status(wo_number)`——四函数均为在途已实现（行 ~165-320），签名核实无误
- Produces: 对四函数的幂等/编号/状态断言；后续 Task 4 HTTP 集成直接复用本组语义

**测试要点（先读懂在途实现再写）：**
- `allocate_wo` 幂等键 = `draft_wo_number`：同 draft 二次申请返回同 `formal_wo_number` 且 `idempotent=True`；
- 正式工单号格式 `WO-HAI-YYYYMMDD-NNN`（当天自增 001 起）；
- `deliver_wo` 缺 wo_number → `{"status": "FAIL"}`；成功 → `{"status": "acknowledged", "queue_position": int}`；
- `manual_review_wo` 成功后 DB 行 status=`manual_review`、queue=`manual_review`（core/hub_db.py 在途迁移已放开该状态）；
- `get_wo_status` 未命中 → `{"status": "not_found"}`；
- **全部走 monkeypatch `hub_api._resolve_paths` 指向 tmp_path，禁止碰真实库**（fixture 写法：monkeypatch.setattr(hub_api, "_resolve_paths", lambda: {...})，db_path=tmp_path/"test.db"）。

- [ ] **Step 1: 写测试文件**（完整代码，勿缩略）：

```python
# -*- coding: utf-8 -*-
"""批0：intake 工单 API 单元测试（temp DB，monkeypatch _resolve_paths）。"""
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import hub_api  # noqa: E402
from core.hub_db import HubDB  # noqa: E402


def _patch_paths(monkeypatch, tmp_path):
    def fake_resolve():
        return {
            "sync_root": str(tmp_path),
            "db_path": str(tmp_path / "hub_meta_test.db"),
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        }
    monkeypatch.setattr(hub_api, "_resolve_paths", fake_resolve)
    # 预建库（含在途迁移：manual_review 状态 + queue/draft_wo_number 列）
    HubDB(str(tmp_path / "hub_meta_test.db")).init_schema()
    return tmp_path


def test_allocate_generates_wo_and_idempotent(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    today = datetime.now().strftime("%Y%m%d")
    first = hub_api.allocate_wo("draft-A", "AKO_quote_agent", "生成报价")
    assert first["status"] == "allocated"
    assert first["formal_wo_number"] == f"WO-HAI-{today}-001"
    assert first["idempotent"] is False

    again = hub_api.allocate_wo("draft-A", "AKO_quote_agent", "生成报价")
    assert again["formal_wo_number"] == first["formal_wo_number"]
    assert again["idempotent"] is True


def test_deliver_wo_pending_and_ack(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    wo = hub_api.allocate_wo("draft-B", "AKO_law_agent", "合规预检")
    ack = hub_api.deliver_wo({
        "wo_number": wo["formal_wo_number"],
        "module": "AKO_law_agent",
        "action": "合规预检",
        "scope": "test",
    })
    assert ack["status"] == "acknowledged"
    assert ack["wo_number"] == wo["formal_wo_number"]
    assert isinstance(ack["queue_position"], int)

    row = hub_api.get_wo_status(wo["formal_wo_number"])
    assert row["status"] == "pending"
    assert row["queue"] == "main"
    assert row["draft_wo_number"] == "draft-B"


def test_manual_review_and_status_lookup(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    wo = hub_api.allocate_wo("draft-C", "AKO_quote_agent", "复杂报价")
    r = hub_api.manual_review_wo({"wo_number": wo["formal_wo_number"], "module": "AKO_quote_agent"})
    assert r["status"] == "queued"
    assert r["queue"] == "manual_review"
    row = hub_api.get_wo_status(wo["formal_wo_number"])
    assert row["status"] == "manual_review"
    assert row["queue"] == "manual_review"


def test_status_not_found(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert hub_api.get_wo_status("WO-HAI-20990101-999")["status"] == "not_found"


def test_deliver_missing_wo_number(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert hub_api.deliver_wo({})["status"] == "FAIL"
```

> HubDB 迁移已在 `core/hub_db.py` 在途 diff 中实现（新列 + CHECK 重建），测试若遇迁移异常按"迁移逻辑缺陷"处理——修复在途代码而不是绕过测试。

- [ ] **Step 2: 运行验证**

```bash
python -m pytest tests/test_intake_wo_api.py -q
```

预期：5 条 PASS。若 FAIL，根因两类：(a) 在途 hub_api/hub_db 逻辑缺陷 → 修代码；(b) 测试语义不符（如 queue 字段默认值）→ 对照在途 diff 修正断言后再跑，直至全绿。

- [ ] **Step 3: Commit**

```bash
git add tests/test_intake_wo_api.py
git commit -m "[batch0][intake] 工单 API 单测：allocate 幂等编号/deliver ACK/manual_review/status AC-03/04/07"
```

---

### Task 4: HTTP 端点集成测试

**Files:**
- Create: `tests/test_intake_wo_http.py`
- Test: 新建测试文件（镜像 `tests/test_heartbeat_http.py` 的进程内起服写法——若该文件写法与下述不符，以仓库既有惯例为准并保持本测试等价语义）

**Interfaces:**
- Consumes: `hub_http_server.HubHTTPHandler`；端点 `POST /api/v1/hub/wo/allocate|deliver|manual_review`、`GET /api/v1/hub/wo/{id}`（在途已实现）
- Produces: HTTP 层四端点契约断言；为 Task 5 手工验收提供脚本基础

- [ ] **Step 1: 写测试文件**

```python
# -*- coding: utf-8 -*-
"""批0：intake 工单 HTTP 端点集成测试（进程内起服 + temp DB）。"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import hub_api  # noqa: E402
import hub_http_server  # noqa: E402
from core.hub_db import HubDB  # noqa: E402


class _TestServer:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hub_api, "_resolve_paths", lambda: {
            "sync_root": str(tmp_path),
            "db_path": str(tmp_path / "hub_meta_test.db"),
            "chroma_root": str(tmp_path / "chroma_db"),
            "file_root": str(tmp_path / "files"),
        })
        HubDB(str(tmp_path / "hub_meta_test.db")).init_schema()
        self.server = HTTPServer(("127.0.0.1", 0), hub_http_server.HubHTTPHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_wo_http_flow(monkeypatch, tmp_path):
    srv = _TestServer(tmp_path, monkeypatch)
    try:
        status, alloc = srv.post("/api/v1/hub/wo/allocate", {
            "draft_wo_number": "draft-http-1",
            "module": "AKO_media_agent",
            "action": "文案生成",
        })
        assert status == 200 and alloc["status"] == "allocated"
        wo = alloc["formal_wo_number"]

        status, ack = srv.post("/api/v1/hub/wo/deliver", {
            "wo_number": wo, "module": "AKO_media_agent", "action": "文案生成",
        })
        assert status == 200 and ack["status"] == "acknowledged"

        status, q = srv.post("/api/v1/hub/wo/manual_review", {"wo_number": wo})
        assert status == 200 and q["queue"] == "manual_review"

        status, row = srv.get(f"/api/v1/hub/wo/{wo}")
        assert status == 200 and row["status"] == "manual_review"
    finally:
        srv.close()


def test_wo_http_missing_draft_400(monkeypatch, tmp_path):
    srv = _TestServer(tmp_path, monkeypatch)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/v1/hub/wo/allocate",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("预期 400 未发生")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        srv.close()
```

- [ ] **Step 2: 运行验证**

```bash
python -m pytest tests/test_intake_wo_http.py -q
```

预期：2 条 PASS。

> **已知缺陷预判（执行时先查后修）**：`hub_api.get_wo_status` 直接 `return row`（sqlite3.Row），HTTP 层 `json.dumps(row)` 不可序列化 → GET 已存在工单会 500。若 `test_wo_http_flow` 的 GET 断言失败且服务端 500，修复 `hub_api.get_wo_status`：`return dict(row)`（先转普通 dict 再返回），保持单测与 HTTP 层共用同一序列化语义。

- [ ] **Step 3: Commit**

```bash
git add tests/test_intake_wo_http.py
git commit -m "[batch0][intake] 工单 HTTP 端点集成测试：allocate/deliver/manual_review/status 全链 AC-03/07"
```

---

### Task 5: 命名拓扑对齐（§九 名单清扫第一刀）

**Files:**
- Modify: `config/agent_names.yaml`（追加 1 条）
- Modify: `config/agent_layers.yaml`（新增"大门层"）

**Interfaces:**
- Consumes: 两份文件的 YAML 结构（`agents:` 映射 / `layers:` 分层映射，结构已核实）
- Produces: 看板 overview/热力对 intake 显示中文名"任务大门"；拓扑归属大门层

- [ ] **Step 1: agent_names.yaml 追加条目**

在 `agents:` 映射内追加（保持两空格缩进风格，位置随意）：

```yaml
  AKO_hub_intake_agent: 任务大门
```

- [ ] **Step 2: agent_layers.yaml 新增大门层**

在 `layers:` 下、`知识层:` 之前新增：

```yaml
  大门层:
    - AKO_hub_intake_agent

```

> 依据方案 §九 第 4 条（大门层单列）。若看板渲染对未知层名报错（渲染逻辑动态取 key，通常安全），回退方案：并入知识层上沿，并在 commit message 注明。

- [ ] **Step 3: 验证**

```bash
python -c "import yaml; n=yaml.safe_load(open('config/agent_names.yaml',encoding='utf-8')); l=yaml.safe_load(open('config/agent_layers.yaml',encoding='utf-8')); assert n['agents']['AKO_hub_intake_agent']=='任务大门'; assert 'AKO_hub_intake_agent' in l['layers']['大门层']; print('OK')"
```

预期：打印 `OK`。

- [ ] **Step 4: Commit**

```bash
git add config/agent_names.yaml config/agent_layers.yaml
git commit -m "[batch0][intake] 命名拓扑对齐：任务大门中文名 + 大门层单列 AC-05"
```

---

### Task 6: 全链路验收 + 整批提交

**Files:**
- 无新建（执行 + 汇总）

**Interfaces:**
- 消费 Task 1-5 全部产出

- [ ] **Step 1: 脚本化端到端验收（真实代码路径，temp DB）**

```bash
python -m pytest tests/test_intake_registration.py tests/test_intake_wo_api.py tests/test_intake_wo_http.py tests/test_hub_api_taxonomy.py tests/test_hub_db_migrate.py -q
```

预期：全绿。随后跑一次真实 hub_api 冒烟（temp DB、真工单链路）确认无环境耦合：

```bash
python - <<'EOF'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import hub_api
from core.hub_db import HubDB
tmp = tempfile.mkdtemp()
hub_api._resolve_paths = lambda: {"sync_root": tmp, "db_path": str(Path(tmp)/"m.db"), "chroma_root": tmp, "file_root": tmp}
HubDB(str(Path(tmp)/"m.db")).init_schema()
a = hub_api.allocate_wo("draft-e2e", "AKO_writer_agent", "技术写作")
assert a["status"] == "allocated", a
ack = hub_api.deliver_wo({"wo_number": a["formal_wo_number"], "module": "AKO_writer_agent"})
assert ack["status"] == "acknowledged", ack
print("E2E-OK", a["formal_wo_number"], ack["queue_position"])
EOF
```

预期：打印 `E2E-OK WO-HAI-YYYYMMDD-001 0`。

- [ ] **Step 2: 回归既有测试 + AC-06 启动无回退证据（如实记录，失败不隐藏）**

```bash
python -m pytest tests/test_hub_api_taxonomy.py tests/test_hub_db_migrate.py tests/test_route_all_spokes.py -q 2>&1 | tail -20
```

> `test_route_all_spokes.py` 为 script 型（模块级执行真实 spoke import/run），若因环境缺依赖失败属已知噪音，记录原因即可；taxonomy 与 migrate 两条必须绿。

AC-06（hub 启动不被 intake 拖慢）证据——验证 hub 侧导入不触发 intake 重依赖：

```bash
python - <<'EOF'
import sys, time
sys.path.insert(0, ".")
t0 = time.time()
import hub_api, hub_http_server, agents.ako_intake_adapter
heavy = [m for m in sys.modules if m.split(".")[0] in ("torch", "chromadb", "langchain", "transformers")]
print(f"import-ok {time.time()-t0:.2f}s heavy_modules={heavy}")
EOF
```

预期：`import-ok` 且 `heavy_modules=[]`（intake 适配器顶层仅 sys.path，spoke 延迟构造）。

- [ ] **Step 3: 手工看板验收（L3 人工在环留痕，如环境允许）**

按 `AKO_hub_start.bat` 启动 hub，在员工台发一条含"工单/帮我"的自然语言 → 预期命中 intake（状态 pending/manual_review 可见）→ 结果写一行到 `logs/batch0_intake_acceptance_2026-09-02.md`。环境不可起时如实标注"跳过，原因：xxx"，不可伪造通过。

- [ ] **Step 4: 整批提交（含全部在途文件 + 本批新文件）**

```bash
git add agents/ako_intake_adapter.py config/routing_rules.yaml registry/workflows.py core/hub_db.py hub_api.py hub_http_server.py registry/taxonomy.py config/agent_names.yaml config/agent_layers.yaml tests/ docs/AKO_hub_agent_connect_plan_v1.0.0.md docs/superpowers/plans/2026-09-02-batch0-intake-wiring.md
git commit -m "[batch0][intake] intake 接线收尾提交：适配器+工单API(allocate/deliver/manual_review)+DB迁移+HTTP端点+taxonomy/命名拓扑+测试 8 项 AC-01~10 全过（2026-09-02）"
```

> **禁止** `git add -A`/`git add .`：运行时噪音（`chroma_db/chroma.sqlite3`、`hub_meta.db.bak.20260902_162809`、`registry/http_registered_agents.json` 时间戳）留在工作区不进本批。

- [ ] **Step 5: 提交后复核**

```bash
git status --short && git log --oneline -6
```

预期：在途 7 项 M/新增均已提交，仅剩噪音 3 项未跟踪/未提交；日志可见 Task 1-5 的独立 commit + 本批 commit。

- [ ] **Step 6: 写验收记录**

在 hub `logs/` 追加 `batch0_intake_acceptance_2026-09-02.md`：逐行记录 AC-01~AC-10 判定与证据（测试输出、E2E 结果、Step 3 手工看板结果或跳过原因），提交该记录文件。**AC-01 判定口径**：intake 的真实 spoke 返回值校验由 D:\AKO\AKO_hub_intake_agent 仓库自身 tests 覆盖；hub 侧证据 = Task 2 协议签名/可调用冒烟 + 本文件记录的口径声明，不得虚报"跑过真实 run()"。

```bash
git add logs/batch0_intake_acceptance_2026-09-02.md
git commit -m "[batch0][intake] 验收记录 AC-01~10 留痕"
```

---

## 批 1 后续（不在本计划内，登记解锁条件）

批 1 的 11 个外部目录 + 5 个虚拟 spoke 需先在各 Agent 仓库补 spoke（方案 §六 第 1 步），hub 侧登记任务（SPOKE_REGISTRY/routing/命名）在对应 spoke 就位后按本批 Task 2/5 同款模式逐 agent 施工——hub 侧登记解锁条件：该 agent 的 `spoke.py` 已提交且 `run()` 可通过本仓库的 import+调用冒烟。批 1 正式计划待批 0 验收记录归档后另行产出（一段一段跑通）。
