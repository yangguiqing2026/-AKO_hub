---
title: "AKO Hub 全舰队 Agent 接通施工方案"
description: "D:\\AKO 全舰队 Agent 分批接入 hub 调度（适配器+全路由层注册+命名拓扑）施工规范与验收基线；v1.0.1 附执行终局与口径勘误"
author: "AKO_studio"
date: "2026-09-03"
version: "v1.0.1"
tags: [agent, workflow, config, deploy]
---

# AKO Hub 全舰队 Agent 接通施工方案

> **文档定位**：本方案是 AKO_hub（D:\AKO\AKO_hub）将 D:\AKO 项目内全部 Agent 接入 hub 调度体系的施工方案（施工规范 + 批次清单 + 验收基线）。以 AKO_writer_agent 与 AKO_hub_intake_agent 两次已跑通的接线为样板，将其固化为标准动作。
>
> **审签状态**：草案待审签。施工动作遵循"一段一段跑通"节奏，批间整批回归。

---

## 一、元信息

| 字段 | 内容 |
|:---|:---|
| 文档编号 | AKO_HUB_AGENT_CONNECT_PLAN_v1.0.1 |
| 施工对象 | D:\AKO 下 40 个 Agent/服务目录 + hub 内 5 个虚拟 spoke |
| 编制依据 | AKO_hub_whitepaper_v2.0.0.md、AKO_hub_deploy_checklist_v2.0.0.md、core/spoke_protocol.py、registry/workflows.py、config/routing_rules.yaml、writer/intake 接线样板（commit b804169 与在途改动） |
| 审签状态 | 草案待审签 |
| 生效日期 | 待审签 |
| 修订策略 | 随 spoke 契约或路由层结构变更即时修订；批次完结并入季度巡检 |

---

## 〇、v1.0.1 勘误与执行终局（2026-09-03，本段为权威执行口径）

> v1.0.0 的批次表（批2=工具层 10 个 NL 接通、批3=运维层 13 个 NL 接通）在实施中被
> AKO_studio 拍板修正：**GUI/内部工具/治理服务不做 NL 路由**，改为 L0 注册级
> （看板可见 + taxonomy 分类 + 禁 hub 调度护栏）。本节点取代 §七 中对应批次的施工目标。

### 执行终局（批 0-批 3，2026-09-03 全部落地）

| 批次 | 原口径 | 执行口径 | 结果 |
|:---|:---|:---|:---|
| 批0 | intake 接线收尾 | 同左 | ✅ L3 闭环：工单 API（allocate/deliver/manual_review/status）+ DB 迁移 + taxonomy + 命名大门层；生产 HTTP 全链验证 |
| 部署层 | — | 追加（用户拍板） | ✅ hub 主服务（app.py :8080+worker :5000）、看板 :8081、pending 消费循环、心跳恢复 |
| 批1 | 11 目录 + 5 虚拟 | 同左（layout 挂账后消解） | ✅ NL 接通（architect/law/quote/media/drawing/business/image/netwatch/knowledge）+ 虚拟归档；layout 依赖装齐真实排版链通过 |
| §九 | 名单清扫 | 同左 | ✅ AKO工作流→AKO_workflow、路由"文章"冲突消除、心跳别名×3、三表对齐固化测试 |
| 批2 | 10 个 NL | **修正：8 L0 + 2 全接通** | ✅ chart/art/web_consult/git_push/pack/pipeline/file_tag_manager/review_runner 注册级（manual_gui）；standard/client_profile 全接通（生产全链 done×2，纯本地规则链） |
| 批3 | 13 个 NL | **修正：13 全 L0** | ✅ registry/audit/qc/guardian/monitor/identity_service_agent + clinic/devil/cluster_guardian/config_audit/evolution/dependency_map/kb_agent |

### 关键机制新增（随施工沉淀）
1. `core/pending_worker.py`：pending 队列认领式消费（可路由才执行/不可路由转人工/复用分布式锁），随 :8080 生命周期；
2. `invoke_mode=manual_gui` 注册制 + task_router/pending_worker 双护栏：L0 实体禁 hub 调度；
3. 心跳 `*_agent` 别名表与 registry 规范 id 对齐，看板中文名全覆盖。

### 验收基线（全量）
- 核心测试套件 90/90 绿；生产库终态：41 注册实体、board 39 卡、在线 11/11 中文名齐。
- 挂账项：architect 真实文生图链（密钥+模型下载，用户侧）；media news_monitor 源 URL 配置；file_tag 幽灵卡数据源根治（小项）。
- 验收留痕：hub `logs/`（batch0/batch1*/batch2/deferred/deploy_acceptance 各记录文件）+ 本会话 25+ commits（master，含 [batch*]/[sweep]/[batch][worker] 前缀可检索）。

---

## 二、目标与范围

**目标（一句话）**：D:\AKO 全舰队 Agent 按统一契约接入 hub 调度，形成"看板可见 → 路由可命中 → 调度可执行 → 工单可闭环"的分级接通；每批以真实链路测试闭环验收。

**范围**：

1. 覆盖 D:\AKO 下全部 `AKO_*_agent` 目录（含无 `_agent` 后缀的服务目录 AKO_identity_service / AKO_review_runner / AKO_file_tag_manager / AKO_knowledge）；
2. 覆盖 hub 仓库内虚拟 spoke（AKO_chat / AKO_reports / AKO_form_extractor / AKO_geo / AKO_workflow）——只做归档核对，不新增 agent 侧工程；
3. 明确排除：AKO_hub（圆心本体）、AKO_shared（共享模块）、AKO_logo（素材库）、ako_agent_env / .venv 等环境目录；
4. 本方案**只定契约与批次**，不代各 Agent 仓库执行；实施由各仓库会话照契约施工，回到 hub 侧统一验收。

---

## 三、现状基线（2026-09-02 盘点）

### 3.1 已接线资产

| 层 | 现状 | 清单 |
|:---|:---|:---|
| 适配器 | hub `agents/` 下 17 个 importlib 适配器（含在途未提交的 intake） | architect/business/chat/drawing_inspector/form_extractor/geo/image_analyzer/intake/knowledge/law/layout/media/netwatch/quote/reports/workflow/writer |
| 路由 | keyword_routes 覆盖 13 个 agent_id；composite_tasks 5 条（报价/媒体内容/图纸审查/建筑设计报价/数据提取报表） | quote/media/layout/drawing_inspector/reports/image_analyzer/netwatch/business/knowledge/writer/architect/law/intake |
| Spoke（agent 侧可导入入口） | 仅 3 个具备 | AKO_writer_agent（bootstrap.py+spoke.py，样板）、AKO_law_agent（spoke_adapter.py）、AKO_hub_intake_agent（ako_intake.adapters.spoke） |
| HTTP 注册 | `registry/http_registered_agents.json` 仅 2 条 | AKO_audit_agent / AKO_law_agent（旁路旧机制，本方案不扩展，保留兼容） |
| 命名拓扑 | agent_names 37 条 / agent_layers 3 层 34 条 / agent_edges | 见 §9 漂移清扫 |

### 3.2 已确认问题

1. **名单口径漂移**：`AKO_identity_service` vs `AKO_identity_service_agent`、`AKO_knowledge` vs `AKO_knowledge_agent`、`AKO_review_runner` vs `AKO_review_runner_agent`、`AKO_file_tag_manager` vs `AKO_file_tag_manager_agent`；drawing_inspector 路由短名缺 `_agent` 后缀。短名制式统一为**去 `AKO_` 前缀、去 `_agent` 后缀**。
2. 40 个目录中仅 3 个有可导入 spoke，其余入口为 app.py（Gradio/Web GUI）或 main.py（CLI）——无统一调度入口。
3. GUI 型 agent（art/chart/quote 等 app.py 人机交互）无法无人化调度，需"人工在环"标注。
4. 在途 intake 接线（适配器/routing/workflows 已改未提交）缺验收留痕。

---

## 四、接通分级标准

| 级别 | 含义 | 达标判定 | 目标 Agent 示例 |
|:---|:---|:---|:---|
| L0 | 拓扑/卡片可见 | 看板 overview/热力/拓扑出现卡片，中英文名正确 | 批 3 运维层未定级 agent |
| L1 | 路由直派 | keyword 命中 → importlib 派发 → spoke 执行 → 输出落 hub 目录 → 状态回写 → 看板闭环 | 批 1 全部 |
| L2 | 复合任务 | 参与 composite_tasks sequence 且跑通整链 | layout/quote/media/architect/reports/form_extractor 等既有复合链参与者 |
| L3 | 工单闭环 | P0 消歧/编号/投递/ACK 全链 + 人工在环留痕 | intake/law/writer |

> 接通的**最低基线是 L1**；GUI/人工在环 agent 承诺跑到"产出待确认点"并回写 pending 状态即可算 L1 达标。

---

## 五、统一契约

### 5.1 SpokeAdapter 协议（权威定义）

`core/spoke_protocol.py`，所有 spoke 必须实现：

```python
def run(self, intent="", project_tag="",
        _hub_output_dir="", _hub_db_path="",
        _hub_chroma_root="", _hub_file_root="", **kwargs) -> dict:
    # 返回 {output_files: list[str], summary: str, error: str|None}
```

hub 侧以 `validate_spoke_output()` 校验返回值；不合法视为执行失败。

### 5.2 接线五层注册链（一处不漏）

```
① agent 仓库 spoke（bootstrap.py + spoke.py）
② hub agents/ako_<x>_adapter.py
③ registry/workflows.py → SPOKE_REGISTRY 条目
④ config/routing_rules.yaml → keyword_routes / composite_tasks
⑤ config/agent_names.yaml + agent_layers.yaml + agent_edges.yaml + taxonomy 短名
```

---

## 六、施工标准动作（每 Agent 8 步）

| # | 动作 | 位置 | 说明/样板 |
|:---|:---|:---|:---|
| 1 | 建/验 agent 侧 spoke | 各 Agent 仓库 | 无入口则新建 `bootstrap.py`（虚拟包注册）+ `spoke.py`；模板见附录 A；可无 hub 独立 dry-run |
| 2 | hub 侧适配器 | `agents/ako_<x>_adapter.py` | sys.path + bootstrap 导入，**延迟构造**防 hub 启动被重依赖拖慢；模板见附录 B |
| 3 | SPOKE_REGISTRY 注册 | `registry/workflows.py` | workflow_id/spoke_type/entry_module/entry_function/required_kb_ids/output_dir/description/status=registered/source_dir/invoke_mode=importlib |
| 4 | 路由配置 | `config/routing_rules.yaml` | 中文业务词 ≥3 条 + confidence；可复合者补 composite_tasks |
| 5 | 命名对齐 | 3 个 yaml + taxonomy | 短名制式（去 AKO_/去 _agent），name_zh 按体系中文名 |
| 6 | 看板可见验证 | 启动 hub 查 API | overview/热力/拓扑出现卡片、中英文正确 |
| 7 | 链路验收 | 看板真实发单 | 命中→派发→执行→落盘→回写→闭环；≥1 条真实业务 + 1 条 mock 冒烟 |
| 8 | 单测入库 | hub `tests/` + agent 侧 | 适配器冒烟测试；agent 侧 spoke 自测 |

---

## 七、批次划分与排期

> 口径：按"已接入度"分批（Approach A，2026-09-02 AKO_studio 确认）。每批边界可因 agent 实际接口调整，批内可并行，**批间必须整批回归**（§8 AC-08）。

### 批 0 — 在途收尾（intake，预计 1-2 天）

| 项 | 内容 |
|:---|:---|
| 动作 | 完成 intake 接线 8 步验收（适配器/routing/workflows 已在途），补链路测试留痕后提交（含各仓库侧一致提交） |
| 交付 | intake 达到 L3 基线（工单闭环 + 大门门禁联动） |

### 批 1 — 已接线 agent 补闭环（11 个目录 + 5 虚拟 spoke 核对，预计 3 周内弹性推进）

| Agent 目录 | hub 短名 | 目标深度 | 备注 |
|:---|:---|:---|:---|
| AKO_writer_agent | writer | L3 | 样板，已有 spoke |
| AKO_law_agent | law | L3 | 已有 spoke_adapter.py |
| AKO_architect_agent | architect | L2 | 既有 建筑报价/方案设计 复合链 |
| AKO_quote_agent | quote | L2 | 复合链核心参与者 |
| AKO_layout_agent | layout | L2 | 复合链核心参与者 |
| AKO_media_agent | media | L2 | 复合链核心参与者 |
| AKO_business_agent | business | L1 | — |
| AKO_drawing_inspector_agent | drawing_inspector | L2 | 图纸审查复合链 |
| AKO_image_analyzer_agent | image_analyzer | L1 | GUI 混合，人工在环 |
| AKO_netwatch_agent | netwatch | L1 | — |
| AKO_knowledge | knowledge | L1 | 无 _agent 后缀目录，命名对齐重点 |
| （虚拟）AKO_chat / AKO_reports / AKO_form_extractor / AKO_geo / AKO_workflow | — | L1 | 只核对 hub 内部 spoke 不缺失，归档即可 |

### 批 2 — 工具层其余（10 个目录，批 1 后启动）

| Agent 目录 | hub 短名 | 目标深度 | 备注 |
|:---|:---|:---|:---|
| AKO_pack_agent | pack | L1 | 构建/打包类 |
| AKO_pipeline_agent | pipeline | L1 | 流水线编排类 |
| AKO_standard_agent | standard | L1 | 企业标准类 |
| AKO_client_profile_agent | client_profile | L1 | — |
| AKO_web_consult_agent | web_consult | L1 | Web 咨询 |
| AKO_chart_agent | chart | L1 | GUI，人工在环 |
| AKO_art_agent | art | L1 | GUI，人工在环 |
| AKO_git_push_agent | git_push | L1 | 运维工具类，注意触发授权 |
| AKO_review_runner | review_runner | L1 | 无 _agent 后缀目录 |
| AKO_file_tag_manager | file_tag_manager | L1 | 无 _agent 后缀目录 |

### 批 3 — 运维/治理/知识层（13 个目录，批 2 后启动）

| Agent 目录 | hub 短名 | 目标深度 | 备注 |
|:---|:---|:---|:---|
| AKO_registry_agent | registry | L1 | 注册中心，注意与 http_registered_agents.json 兼容 |
| AKO_audit_agent | audit | L1 | 治理审计，HTTP 注册旁路保留 |
| AKO_qc_agent | qc | L1 | 质检 |
| AKO_clinic_agent | clinic | L1 | 集群健康诊疗 |
| AKO_devil_agent | devil | L1 | 对抗评审 |
| AKO_guardian_agent | guardian | L1 | 安全守卫 |
| AKO_cluster_guardian_agent | cluster_guardian | L1 | 集群巡检 |
| AKO_config_audit_agent | config_audit | L1 | 配置审计 |
| AKO_evolution_agent | evolution | L1 | 体系进化 |
| AKO_dependency_map_agent | dependency_map | L1 | 依赖图谱 |
| AKO_monitor_agent | monitor | L1 | 熔断监控 |
| AKO_identity_service | identity_service | L1 | 身份认证服务，无 _agent 后缀 |
| AKO_kb_agent | kb_agent | L1 | 知识层 |

> 排期节奏遵循"一段一段跑通"，不设硬性截止；建议每 Agent 1-2 天（agent 侧 0.5-1 + hub 侧 0.5 + 联调验收）。

---

## 八、验收标准

### 8.1 每 Agent 验收核对表（施工留痕，落 hub `logs/` 或 commit message）

| 编号 | 验收项 | 判定 |
|:---|:---|:---|
| AC-01 | spoke 返回值过 `validate_spoke_output()` | 通过 |
| AC-02 | SPOKE_REGISTRY 条目字段齐（含 source_dir/invoke_mode/status=registered） | 通过 |
| AC-03 | routing 关键词逐一命中正确 agent（≥3 条中文词 + 单测） | 通过 |
| AC-04 | 真实链路 1 次：看板发单→输出文件落 hub 目录→hub_db 状态→UI 可见 | 通过 |
| AC-05 | agent_names/layers/edges/taxonomy 无漂移无幽灵条目（短名制式） | 通过 |
| AC-06 | hub 启动时间不回退（延迟导入生效，新 spoke 不拖慢启动） | 通过 |
| AC-07 | 适配器冒烟单测入库 hub `tests/` | 通过 |
| AC-08 | 批次回归：既有 agent 路由/链路不破 | 通过 |
| AC-09 | GUI/人工在环 agent 产物停"待确认点"且状态可查 | 通过 |
| AC-10 | 改动留痕：hub 与各 agent 仓库均有提交，message 标注批次与 AC 编号 | 通过 |

### 8.2 批次验收

每批完结做一次整批回归：批内全部 agent AC-01~10 通过 + hub 启动/看板/路由全量冒烟（`verify.py`/`tests/` 现有用例全绿）。

---

## 九、名单漂移清扫（全局一次性动作，批 0 内完成）

1. `agent_names.yaml` / `agent_layers.yaml` / `agent_edges.yaml` 三份名单与 taxonomy 短名制式对齐；
2. 统一目录名（identity_service/knowledge/review_runner/file_tag_manager 等）与短名映射；
3. 清幽灵条目（曾注销的 agent 不再出现于任一名单）；
4. 补齐 AKO_hub_intake_agent 等新增 agent 的 name_zh 与分层归属（大门层建议单列或入知识层上沿）；
5. 清扫结果以 commit 留痕，并在看板拓扑/热力全量核对。

---

## 十、风险与对策

| 风险 | 影响 | 对策 |
|:---|:---|:---|
| 跨 40 仓库改动各自 git，契约版本漂移 | 接线不一致 | 契约只存 hub（本方案 + spoke_protocol），agent 侧照抄；改契约走方案修订流程 |
| spoke 导入重依赖拖慢 hub 启动/内存膨胀 | 服务不可用 | 适配器延迟构造（intake `_spoke()` 模式）；重度 agent 评估子进程隔离 |
| GUI 型 agent 无法无人调度 | 批次延期 | 人工在环标注，验收只到"待确认点" |
| 命名漂移导致路由/卡片错位 | 派发错 agent | §9 全局清扫 + AC-05 逐 agent 校验 |
| 复合任务链上某 agent 未接 | 整链失败 | 复合链参与者在批 1 同批接通后再开放该链 |
| intake 在途改动与批 0 冲突 | 返工 | 批 0 先行收尾提交，再动后续批次 |

---

## 十一、实施组织

1. **本方案**：契约 + 批次 + 验收的单一权威源（存 hub 仓库 docs/）；
2. **实施**：各 Agent 仓库会话照 §6 八步执行，hub 侧改动在 hub 仓库进行并逐 agent 回 hub 验收；
3. **提交规范**：commit message 标注 `[batchN][agent_x] AC-0X~AC-10` 形式留痕；
4. **节奏**：一段一段跑通；每批完结由 hub 侧执行 8.2 整批回归并记录结果。

---

## 附录 A — agent 侧 spoke 模板（bootstrap.py + spoke.py）

```python
# bootstrap.py（agent 仓库根，目录名含下划线时虚拟包注册）
# 参考 AKO_writer_agent/bootstrap.py 与 AKO_hub_intake_agent
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# spoke.py（agent 仓库根）
"""SpokeAdapter 兼容入口：run() 为 hub 唯一调用面。"""
from typing import Any, Dict

def run(intent: str = "", project_tag: str = "",
        _hub_output_dir: str = "", _hub_db_path: str = "",
        _hub_chroma_root: str = "", _hub_file_root: str = "",
        **kwargs: Any) -> Dict[str, Any]:
    # 1) 解析 kwargs（如 topic/doc_type/target_length）→ 调本 agent 业务主流程
    # 2) 产出写入 _hub_output_dir（缺省 fallback 本地 output/）
    # 3) 返回 {output_files: [...], summary: "…", error: None}
    # 4) 失败时返回 error 描述；GUI/人工在环场景返回 human_approval_status=pending
    ...
```

## 附录 B — hub 侧适配器模板（agents/ako_<x>_adapter.py）

```python
"""AKO_<x>_agent — Hub 侧适配器（SpokeAdapter 协议，参考 ako_writer_adapter）"""
import sys
from pathlib import Path
from typing import Any, Dict

SOURCE_DIR = Path(r"D:\AKO\AKO_<x>_agent")

def _load_bootstrap() -> None:          # sys.path + spec 加载 bootstrap（幂等）
def _run_async(coro): ...

def run(intent="", project_tag="", _hub_output_dir="", _hub_db_path="",
        _hub_chroma_root="", _hub_file_root="", **kwargs) -> Dict[str, Any]:
    # 延迟 import spoke → 构造任务 → 轮询至终态 → 结果落盘 → 三字段返回
```

## 附录 C — 每 Agent 验收核对表（施工时逐行勾选）

见 §8.1 AC-01~AC-10 表；落痕方式：commit message 附 `[batchN][shortname] AC-01~10 pass`。

## 附录 D — 引用文件

| 文件 | 位置 |
|:---|:---|
| core/spoke_protocol.py | D:\AKO\AKO_hub |
| registry/workflows.py | D:\AKO\AKO_hub |
| config/routing_rules.yaml | D:\AKO\AKO_hub |
| config/agent_names(_layers/_edges).yaml | D:\AKO\AKO_hub |
| AKO_hub_whitepaper_v2.0.0.md | D:\AKO\AKO_hub |
| AKO_hub_intake_design_plan_v1.0.0.md | D:\AKO |
| AKO_writer_agent/bootstrap.py + spoke.py | D:\AKO\AKO_writer_agent |
| AKO_hub_intake_agent/ako_intake/adapters/spoke.py | D:\AKO\AKO_hub_intake_agent |

---

## 签章区

| 项目 | 内容 |
|:---|:---|
| 起草 | AKO_studio（2026-09-02） |
| 审签 | 待 AKO_studio 人工签章（禁止自动化） |
| 生效日期 | 待定 |
| 下次审阅 | 生效后 3 个月 |

---

> 本方案遵循 AKO 体系文档规范。契约变更（§五）须修订本方案并经审签；各 Agent 仓库 ACTIVE 文件修改按各自体系流程执行。
