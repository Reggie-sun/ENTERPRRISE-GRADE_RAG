# Retrieval Phase 1B GLM Prompt

## 这一阶段做什么

在 Phase 1A 基础上，开始推进 supplemental 阈值校准的工程准备，但仍然不扩主契约。

**注意：当前阶段应按 `1B-A / 1B-B` 两段理解。**

- `1B-A`：先补实验能力、diagnostics 一致性、关键回归、实验记录
- `1B-B`：在补齐 `supplemental_expected=true` 的 verified 样本，并具备部门隔离视角的评估能力后，再做真正的阈值定版

重点是：

- 使用内部真源 `_internal_retrieval_controls`
- 用固定样本比较多组阈值
- 让 diagnostics 和实际判定一致
- 补齐关键回归测试

---

## 当前 readiness 结论（2026-04-02 capability audit 更新）

截至当前仓库状态：

- `eval/retrieval_samples.yaml` 已经有稳定 baseline，且已补入 `12` 条 `supplemental_expected=true` 的 cross-dept 样本
- baseline 可稳定复跑，当前最新评估中 `top1_accuracy / topk_recall / expected_doc_coverage_avg` 均为 `100%`
- 但这 12 条 cross-dept 样本当前仍是 **index-verified, auth-provisional**
- 现有评估脚本仍以 `sys_admin` 身份登录，`requester_department_id` 只是标签，不是真实 auth 视角
- 因此当前 `supplemental_recall` 仍会是 `0.0`，这反映的是 **部门隔离前置条件未闭环**，不是阈值已经校准完成

### 1B-B 不可启动——四个 blocker（三个递进 + 一个验证）

经过 2026-04-02 capability audit 收口，确认 **1B-B 不可启动**。

---

#### 已证实的事实

1. **`eval/retrieval_samples.yaml`** 现有 31 条 verified 样本，其中 12 条 `supplemental_expected: true`
2. 最新评估结果（`eval_20260402_154413.json`）：`top1_accuracy=1.0`, `topk_recall=1.0`, `expected_doc_coverage_avg=1.0`, `supplemental_precision=null`, `supplemental_recall=0.0`, `conservative_trigger_count=0`
3. 所有 12 条 cross-dept 样本的 `supplemental_triggered=false`——因为部门优先路由未启用
4. `scripts/eval_retrieval.py` 默认使用 `sys.admin.demo` 登录，该账号 `data_scope=global`，因此 `_should_use_department_priority_routes()` 返回 `False`，部门优先检索不启用
5. `retrieval_service.py:1296-1307` 中 `_should_use_department_priority_routes()` 对 `data_scope=global` 返回 `False`
6. `backend/app/bootstrap/identity_bootstrap.json` 包含 13 个部门：`dept_integrated_technology`, `dept_research_and_development`, `dept_marketing_management_center`, `dept_production_management`, `dept_production_technology`, `dept_installation_service`, `dept_enterprise_management`, `dept_finance`, `dept_digitalization`, `dept_quality_assurance`, `dept_supply_management`, `dept_general_manager_office`, `dept_project_management`——**不包含 `dept_after_sales` 和 `dept_assembly`**
7. `data/documents/doc_20260321070337_445684f4.json`（123.txt）的 `department_ids` 为空数组、`visibility=private`
8. `backend/tests/test_retrieval_diagnostics.py` 当前结果为 **4 failed, 6 passed**，失败原因均为 401 Unauthorized（测试未注入 auth context）
9. `backend/app/services/retrieval_scope_policy.py` 中 `build_department_priority_retrieval_scope()` 依赖文档的 `department_id` / `department_ids` 做部门分区

---

#### 合理推断但尚未完全证实

1. **当前本地 eval corpus 的文档 metadata 无法支撑部门级检索隔离闭环**：已抽检 `doc_20260321070337_445684f4.json` 确认 `department_ids=[]`、`visibility=private`；但尚未逐一检查 `data/documents/` 下所有文件。基于 `retrieval_scope_policy.py:147-148` 的逻辑，若文档 `department_ids` 为空且 `visibility=private`，则 `_normalize_department_scope()` 返回空列表，`is_department_match` 始终为 `False`，导致 `department_document_ids` 为空——因此即使部门优先路由启用，本部门池也为空，supplemental 不会因"本部门不足"而正确触发。
2. **Blocker 2 同时意味着即使文档有 department_id，eval 语义也难以对齐**：因为 `dept_after_sales` / `dept_assembly` 在 bootstrap 中不存在，无法创建对应身份的登录会话来模拟部门视角。

---

#### 当前仍缺证据的部分

1. `data/documents/` 下是否**所有**已索引文档都缺少 `department_id`——仅抽检了一份，不能断言"全部"。完整的全量检查需要遍历所有文档 metadata 文件或查询数据库。
2. 生产环境 Qdrant 中已索引文档的 payload 是否包含 `department_id`——本地 `data/documents/*.json` 是 metadata 快照，可能与 Qdrant payload 不同步。
3. ~~`retrieval_service.py` 中 `call_retrieval()` 未将 `department_id` 传入请求~~ —— **已确认**：`POST /api/v1/retrieval/search` 的请求模型 `RetrievalRequest` 不含 `department_id` 字段，部门视角来自 `auth_context`（登录后的 token），而非请求体。`call_retrieval()` 接收 `department_id` 参数仅作为签名预留，实际未使用是正确行为。

---

#### Blocker 1（底层 metadata）：当前本地 eval corpus 无法支撑部门级检索隔离闭环

- 已抽检 `data/documents/doc_20260321070337_445684f4.json`：`department_ids=[]`, `visibility=private`
- `RetrievalScopePolicy.build_department_priority_retrieval_scope()` 依赖文档的 `department_id` / `department_ids` 区分本部门 vs 跨部门
- **推断后果**（基于代码逻辑，非实测）：任何非 sys_admin 用户查任何 query，`department_document_ids` 都为空，所有文档都在补充池
- **未证实部分**：尚未逐一检查所有文档 metadata；仅基于单一样本 + 代码逻辑推断
- 这意味着本部门检索可能永远是 0 结果，supplemental 不会因"本部门不足"而正确触发

#### Blocker 2（身份层）：eval 样本的部门 ID 与生产 identity 不匹配

- `eval/retrieval_samples.yaml` 使用 `dept_after_sales`, `dept_assembly`, `dept_digitalization`
- `backend/app/bootstrap/identity_bootstrap.json` 包含 13 个部门，**已确认不包含 `dept_after_sales` 和 `dept_assembly`**
- `dept_digitalization` 存在于 bootstrap 中
- 这两个部门仅存在于 `test_authorization_filters.py` 的**测试专用** bootstrap 中
- 即使文档有 department_id，如果账号身份无法匹配样本定义，eval 结果无法解释

#### Blocker 3（eval harness 层）：脚本始终以 `sys_admin` 运行，department-priority 路由不启用

- `scripts/eval_retrieval.py` 默认使用 `sys.admin.demo`（`data_scope=global`）
- `retrieval_service.py:1296-1307` 中 `_should_use_department_priority_routes()` 对 `data_scope=global` 返回 `False`
- `build_department_priority_retrieval_scope()` 永远不被调用
- `supplemental_triggered=false`（非 null），但 `primary_threshold` / `trigger_basis` 等阈值判定字段为 `null`——因为部门优先路由未启用，这些字段不会被填充
- **注意**：`RetrievalRequest` 不含 `department_id` 字段（参见 `backend/app/schemas/retrieval.py`），部门视角来自 `auth_context` 而非请求体。`requester_department_id` 只是样本标签，没有映射到真实非全局 auth 身份，因此当前 eval 无法代表真实部门视角

---

#### Blocker 4（测试验证）：diagnostics 测试套件当前 4 failed / 6 passed

- `backend/tests/test_retrieval_diagnostics.py` 当前 **4 failed, 6 passed**
- 4 个失败均为 401 Unauthorized——`TestRetrievalObservability` 和 `TestRetrievalExplainability` 中的测试通过 `TestClient(app)` 直接调用 `/api/v1/retrieval/search`，但未注入 auth context，认证收紧后被拒绝
- **这组失败不应被表述为"预期通过"或"已验证通过"**
- 6 个通过的测试是纯单元测试（不经过 HTTP endpoint 或已正确 mock auth），不涉及认证问题
- 最小修复方案：为失败的 4 个测试添加 auth dependency override（参考同文件 `test_retrieval_snapshot_replay` 中 `_admin_auth` 的做法），但不属于本轮 audit 范围

**四个 blocker 的依赖关系**：Blocker 3 即使修好了（换非 sys_admin 账号），Blocker 1（文档缺 department_id）仍会让部门优先检索无法正确分区；Blocker 2（部门 ID 不匹配）意味着即使有 department_id，eval 语义也难以对齐。Blocker 4 不阻塞 1B-B 功能，但意味着 diagnostics 回归测试当前不可作为验证手段。

这意味着：

- **`1B-A` 已基本完成**（阈值实验能力、diagnostics 结构、评估脚本、31 条 verified 样本）
- **样本数量层面的 blocker 已解除**
- **但 1B-B 无法启动，原因是底层 metadata + 身份层 + eval harness 三重缺失，外加测试验证不可用**
- 要推进 1B-B，需要按顺序解除 Blocker 1 → Blocker 2 → Blocker 3
- Blocker 4 应在 1B-B 启动前修复，但不阻塞功能准备

当前阶段允许做：

- 阈值实验能力
- baseline / matrix 对比
- diagnostics 字段一致性收口
- retrieval/chat/SOP 共用规则回归
- 关键触发分支测试
- `1B-B` 前置条件核对与缺口收口（本轮已完成——即本 audit）
- 为 diagnostics 测试补 auth mock（Blocker 4 修复，最小必要改动）
- **文档 department_id 元数据补录**（Blocker 1 的前置工作，可在文档管理中操作）
- **identity bootstrap 部门与 eval 样本对齐**（Blocker 2 的前置工作）
- **全量检查 `data/documents/` 所有文档 metadata 的 department_ids 字段**（补齐 Blocker 1 证据）

当前阶段不要做：

- 在没有真实部门隔离评估的前提下宣称默认阈值已经“调优完成”
- 为了制造正样本，临时篡改 verified baseline
- 扩 public contract 或新开 endpoint 分叉规则

---

## 硬约束

- 必须遵守 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)
- 不新增公开 `system-config` 字段
- 不把 `_internal_retrieval_controls` 暴露到 public response
- 不分叉 `retrieval / chat / SOP` 的 supplemental 规则

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [eval/retrieval_samples.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/retrieval_samples.yaml)
- [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md)
- [system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/system_config_service.py)
- [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- [test_retrieval_chat.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_retrieval_chat.py)
- [test_system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_system_config_service.py)
- `eval/results/` 最新结果

---

## 交付物要求

### 1. 阈值实验能力

优先复用 `scripts/eval_retrieval.py`，不要重复造一个过重的新系统。

可以接受两种方案：

- 给 `eval_retrieval.py` 增加阈值 override / matrix 输入能力
- 或新增一个很薄的 `scripts/eval_threshold_matrix.py` 来驱动多组实验

### 2. 实验记录

- 创建或补充 `eval/experiments/`
- 每组实验至少记录：
  - 阈值组合
  - baseline 对比
  - top1 / recall
  - supplemental 误触发 / 漏触发
  - 关键案例

### 3. 回归和诊断

补齐或增强这类回归：

- `department_sufficient`
- `department_low_quality`
- `department_insufficient`
- fine query 使用更严格阈值
- `truncate_to_top_k=True/False` 的窗口差异

### 4. readiness 说明

必须在产出里明确区分：

- 本轮已经完成的 `1B-A`
- 样本 blocker 已解除、但仍被 auth / metadata / department-isolation 条件阻塞的 `1B-B`

至少要说明：

- 当前 verified 样本是否包含 `supplemental_expected=true`
- 当前是否足以给出默认阈值定版建议
- 如果还不够，下一步缺什么评估能力、auth 映射或部门隔离条件

---

## 验收标准

- 主契约测试继续通过
- retrieval/chat/SOP 行为保持一致
- diagnostics 能反映真实阈值和触发依据
- 没有扩 public contract
- 如果当前样本不足以支撑最终调参结论，必须明确写成 **provisional / blocked for final tuning**

---

## 可直接发给 GLM 的 Prompt

```text
基于当前 1B-A 已基本完成、且 `eval/retrieval_samples.yaml` 已补入 12 条 `supplemental_expected=true` cross-dept 样本的状态，继续推进 Phase 1B。

当前现实边界：

- 样本数量层面的 blocker 已解除
- 但这批 cross-dept 样本当前仍是 index-verified, auth-provisional
- 当前评估脚本仍以 `sys_admin` 身份登录，`requester_department_id` 只是标签，不是真实部门权限视角
- 最新评估里 `supplemental_recall = 0.0`、`supplemental_triggered = 0`，这说明部门隔离前置条件还没闭环，不能直接进入最终阈值定版

任务：
围绕 `1B-B` 的前置条件做核对和收口。可以补齐最小必要的评估能力、诊断或文档说明，但不要把这轮写成“默认 supplemental 阈值已经调优完成”。

必须遵守：
1. 不新增公开 system-config 字段。
2. 不把 _internal_retrieval_controls 暴露到 public response。
3. retrieval / chat / SOP 必须继续共用同一套 supplemental 判定逻辑。
4. 不扩 API 主字段，不改 MAIN_CONTRACT_MATRIX 约束。
5. 不在 `sys_admin` 全量可见视角下强行调默认阈值。
6. 如果给出建议，必须明确区分 provisional 建议 与 final recommendation。

请先确认并输出：
1. 当前 `supplemental_expected=true` verified 样本数
2. 最新评估里的 `supplemental_precision / supplemental_recall / conservative_trigger_count`
3. 当前是否真的具备部门级检索隔离；如果不具备，缺口在 auth profile、metadata 还是 retrieval scope

然后只做下面两类事情之一：
1. 如果仓库里已经具备部门级隔离所需能力：
   - 用最小改动把 eval 跑到真实部门视角
   - 重新执行阈值实验
   - 给出 provisional 阈值建议
2. 如果仓库里还不具备部门级隔离所需能力：
   - 明确列出缺口
   - 补齐最小必要的文档、诊断或脚本支撑
   - 明确说明为什么现在还不能做有意义的 1B-B 定版

不要做的事：
- 不把 auth-provisional 样本说成 fully verified auth behavior
- 不为了制造 supplemental trigger 而篡改 baseline 语义
- 不顺手做与 Phase 1B 无关的大重构

完成后请输出：
1. 修改文件列表
2. 你确认到的当前状态
3. 运行的命令与结果
4. `1B-B` 现在是否可正式开始；如果还不行，卡点是什么
5. 下一步最小可执行动作
```
