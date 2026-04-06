# Retrieval State Snapshot

> 这份文件只用于给 coding agent 提供 retrieval 当前状态快照。
> 真正的 source of truth 仍然是：
> - `MAIN_CONTRACT_MATRIX.md`
> - `RETRIEVAL_OPTIMIZATION_PLAN.md`
> - `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
> - `eval/README.md`
> - `eval/results/` 最新结果
>
> 维护规则：
> - 只要 baseline、运行时阈值、阶段判断、当前 blocker 发生变化，必须同步更新本文件
> - 如果没有同步更新，本文件应视为可能漂移的快照，不能单独作为继续 / 暂停某阶段的判断依据

更新时间： `2026-04-06 10:10`

---

## 1. 当前阶段

- 当前主线： `Phase 1B-B`
- 当前状态: `gate 复核完成，GATE NOT PASSED；发现 2 个新问题：cross-013 department_sufficient 误判 + sop-005 阈值不稳定性`
- `Phase 2A / Gate`: 已完成
- `Phase 2B`: **GATE NOT PASSED — 当前仍不可进入 Phase 2B 正式实现**
- `Phase 3`: 未开始

**当前口径**:
- `cross-007 / cross-009 / cross-010` 的 cross-dept top-k 回退，已在当前工作区代码上收口
- 当前工作区代码在 fresh API (`127.0.0.1:8021`) 上可复现：
  - 31 条原始样本基线：`top1=96.77%, topk=100%, sup_precision=1.0, sup_recall=1.0`
  - 43 条含边界样本：`top1=95.35%, topk=97.67%, sup_precision=0.957, sup_recall=0.957`
- 默认 `localhost:8020` 命中 Docker 容器 `enterprise-rag-api`（由 docker-proxy 绑定端口）
- 当前 gate 复核为保证可重复性，统一使用 `127.0.0.1:8021`；若要改回 8020，需先做环境一致性校验
- **Phase 2B readiness / sample gate 复核已完成，结论：GATE NOT PASSED**（详见下方 §3 最新 eval 结果和 §5 gate 判决）

---

## 2. 当前硬约束

- 不扩稳定主契约，先看 `MAIN_CONTRACT_MATRIX.md`
- `retrieval / chat / SOP` 继续共用同一套 supplemental 判定逻辑
- retrieval 优化顺序必须保持:
  1. `baseline / supplemental`
  2. `chunk`
  3. `router / hybrid`
  4. `rerank`
- 不要把 heuristic 字段当 ground truth
- 不要为了让指标变好看而篡改 verified baseline 语义

---

## 3. 当前 baseline

### 样本状态

- `eval/retrieval_samples.yaml`:
  - `43` 条样本（原 31 条 verified + 12 条新增 boundary/lexical/hybrid/cross-dept 样本）
  - 其中 `23` 条 `supplemental_expected=true`（原 12 + 新增 11）
  - 新增样本均为 `status: unverified`，需经 eval 运行验证后标记

### 最新 eval 结果（含 boundary 样本）

- `eval/results/eval_20260406_100642.json` — 43 条样本 gate 复核 eval
- 运行环境：fresh local uvicorn `http://127.0.0.1:8021`

关键指标：
- `top1_accuracy = 95.35%`（原 31 条为 96.77%，新增样本拉低 1.42pp）
- `topk_recall = 97.67%`（原 100.00%，cross-013 完全未命中）
- `expected_doc_coverage_avg = 97.67%`
- `supplemental_precision = 0.957`（原 1.0，sop-005 保守误触发导致下降）
- `supplemental_recall = 0.957`（原 1.0，cross-013 漏触发导致下降）
- `conservative_trigger_count = 1`（原 0，sop-005 在本轮出现保守误触发）
- `term_coverage_avg = 88.57%`

### 新增样本的 eval 发现

**通过的新样本 (11/12)**:
- `boundary-001` through `boundary-005`: 全部 top1=1.0, topk=1.0, supplemental 正确触发
- `lexical-001`, `lexical-002`: 全部通过，lexical 边界正确处理
- `hybrid-001`: 通过，hybrid->qdrant 降级路径正确
- `hybrid-002`: 通过（same-dept，supplemental_expected=false，未触发，正确）
- `cross-014`, `cross-015`: 通过，cross-dept 方向反转和规范类文档正确召回

**失败的新样本 (1/12)**:
- `cross-013` (皮带轮部品组装 止动螺丝和压装的完整工艺流程, from dept_digitalization):
  - `top1_accuracy=0.0, topk_recall=0.0`
  - 部门返回了 doc_20260326071937_37f67e8c (刀具系统技术要求)，score=0.99
  - 期望文档 doc_20260401092629_f470103f (FAW05皮带轮部品SOP) 完全未出现在结果中
  - supplemental 未触发 (basis=department_sufficient)，因为部门认为已有足够结果
  - **根因**: 当 requester 部门有语义上部分重叠的文档时，department_sufficient 判定阻止了 supplemental 触发，导致真正的目标文档（属于不同部门）被遗漏
  - **这是 Phase 2B readiness gate 的一个新发现**，说明当前 sample 覆盖确实暴露了之前不知道的问题

**新发现的原始样本回归 (1)**:
- `sop-005` (WI-SJ-052 摇臂钻床安全操作规范 4.25 下班后要做什么):
  - 在 31 条基线中：`supp_triggered=false, avg_topn=0.883, basis=department_sufficient` — 无保守误触发
  - 在 43 条基线中：`supp_triggered=true, avg_topn=0.674, basis=department_low_quality` — 出现保守误触发
  - **根因**: `avg_top_n_score` 在两次运行间从 0.883 振荡到 0.674，跨越 `fine_query_avg_top_n_threshold=0.70` 阈值
  - 这说明 **provisional 阈值存在稳定性问题**：Qdrant HNSW 向量搜索的非确定性导致边界 case 的 avg_top_n 在阈值附近振荡
  - sop-005 成为当前唯一一条保守误触发样本，supplemental_precision 从 1.0 降至 0.957

### 阈值覆盖分布（43 条样本）

按 top1_score 分布：
- `< 0.55 (coarse threshold)`: 2 条 (cross-004, boundary-005) — 命中粗粒度低质量区
- `0.55 - 0.95 (boundary zone)`: 7 条 — 命中阈值临界区
  - cross-008 (0.911), boundary-003 (0.905), cross-005 (0.984→0.667 avg)
  - cross-007 (0.918), cross-014 (0.926), cross-011 (0.961), hybrid-001 (0.936)
- `>= 0.95 (fine threshold)`: 34 条 — 原有样本主要分布区

### 当前样本充分性判断（gate 复核后更新）

对”可以进入 Phase 2B 正式实现”的判断：
- **GATE NOT PASSED — 仍不够**
- 新增 12 条样本中 1 条暴露了新的边界问题（cross-013 的 department_sufficient 误判）
- 原始 31 条样本中 1 条出现不稳定行为（sop-005 的 avg_topn 阈值振荡）
- 这证明补样策略是有效的：它确实发现了之前 31 条样本没有覆盖的问题
- 当前 provisional 阈值在 boundary zone 的行为需要进一步分析：
  - `cross-013` 说明当部门有语义重叠文档时，quality thresholds 无法区分”真正的满足”和”语义相似但内容不匹配”
  - `sop-005` 说明 `fine_query_avg_top_n_threshold=0.70` 对非确定性向量搜索结果过于敏感，边界 case 可能跨阈值振荡
  - `cross-004` (top1=0.5) 已经能正确触发 supplemental，说明当 score 极低时 quality guard 工作正常
  - `cross-013` (top1=0.99) 的失败说明 quality guard 在 score 接近 1.0 但语义不匹配时无法捕捉
- 大部分新增样本仍落在高分区域（>0.9），provisional 阈值尚未被真正校准

对”发现当前 blocker / regression”的判断：
- **已足够**
- 新增样本已验证：当前代码在 original 31 条上无新的结构性回归
- sop-005 的保守误触发是阈值振荡导致的非确定性行为，不是代码回退
- 新增样本成功暴露了 cross-013 和 sop-005 两类边界问题

### 运行前置条件

- auth profile 映射已就位:
  - `eval/retrieval_auth_profiles.yaml`
- eval ACL seed 已就位
  - `eval/retrieval_document_acl_seed.yaml`
  - `scripts/seed_retrieval_eval_acl.py`
- PostgreSQL metadata 场景已验证可写入 ACL seed
- eval 已能使用真实部门 token 跑,不再只是 `sys_admin` 视角

### 当前 provisional 阈值

当前运行时保留值:
- `top1_threshold = 0.55`
- `avg_top_n_threshold = 0.45`
- `fine_query_top1_threshold = 0.95`
- `fine_query_avg_top_n_threshold = 0.70`

这是 **provisional**，不是 final recommendation。

### 最新 code-validated baseline 报告

- `eval/results/eval_20260406_081609.json` — 首次 fresh API 验证
- `eval/results/eval_20260406_082413.json` — 可复现性验证（同一工作区代码，不同启动实例）

两次验证结果一致，证明当前代码基线可稳定复现。

验证环境：fresh local uvicorn `http://127.0.0.1:8021`（当前工作区代码）

关键指标（两次一致）:
- `top1_accuracy = 96.77%`
- `topk_recall = 100.00%`
- `expected_doc_coverage_avg = 100.00%`
- `supplemental_precision = 1.0`
- `supplemental_recall = 1.0`
- `conservative_trigger_count = 0`
- `term_coverage_avg = 91.94%`

对比解读:
- `eval/results/eval_20260405_134848.json` (旧 baseline):
  - top1_accuracy = 58.06%
  - topk_recall = 100.00%
- `eval/results/eval_20260405_144807.json` / `eval/results/eval_20260405_150819.json`:
  - top1_accuracy = 90.32%
  - topk_recall = 90.32%
  - 用于记录当时的回退状态，不再视为当前工作区代码的最新 baseline
- `eval/results/eval_20260406_081242.json`:
  - 指向 `localhost:8020` Docker 容器（`enterprise-rag-api`）的结果
  - 该容器实例与 fresh local uvicorn(`127.0.0.1:8021`)不是同一运行实例/环境
  - 当前阶段为避免混用运行实例，未将其作为 gate 复核统一 baseline

**结论**: 当前工作区代码基线在 31 条原始样本上可复现，cross-dept supplemental blocker 已收口。但 **Phase 2B readiness / sample gate 复核已完成，结论为 GATE NOT PASSED**：新增 12 条边界样本暴露了 2 个新问题（cross-013 department_sufficient 误判 + sop-005 阈值振荡），当前 provisional 阈值尚未校准完成。不等于可以进入 `Phase 2B` 正式实现。

### gate 复核 eval 报告

- `eval/results/eval_20260406_100642.json` — 43 条样本 gate 复核 eval

运行环境：fresh local uvicorn `http://127.0.0.1:8021`（当前工作区代码）

关键指标（43 条）:
- `top1_accuracy = 95.35%`
- `topk_recall = 97.67%`
- `expected_doc_coverage_avg = 97.67%`
- `supplemental_precision = 0.957`（sop-005 保守误触发）
- `supplemental_recall = 0.957`（cross-013 漏触发）
- `conservative_trigger_count = 1`
- `term_coverage_avg = 88.57%`

**gate 判决依据**:
1. `cross-013` (department_sufficient 误判): top1=0.99 但语义不匹配，supplemental 未触发 → 证明 quality guard 在高置信度语义重叠时无法区分
2. `sop-005` (阈值振荡): avg_topn 在两次运行间从 0.883 振荡到 0.674，跨越 fine_query_avg_top_n_threshold=0.70 → 证明 provisional 阈值对非确定性向量搜索结果过于敏感
3. 新增样本大部分仍落在高分区域（>0.9），provisional 阈值 (0.55/0.45) 尚未被真正校准

**gate 判决: GATE NOT PASSED**

### 8020 端口根因分析

**观察到的现象**:
- `localhost:8020` 命中 Docker 容器 `enterprise-rag-api`（docker-proxy 绑定端口）
- `docker inspect enterprise-rag-api` 显示容器使用 `uvicorn ... --reload`，并 bind 挂载 `/home/reggie/vscode_folder/Enterprise-grade_RAG:/app`
- fresh local uvicorn 在 `127.0.0.1:8021` 独立运行（不是 8020 那个容器实例）
- `make eval-retrieval` 默认 `API_PORT=8020`，因此默认命中容器实例

**注意**: 当前证据支持“8020 与 8021 是不同运行实例，不应混用为同一轮 gate baseline”；不支持“8020 一定是旧代码”。

**当前解决方案**:
- gate 复核统一使用 `127.0.0.1:8021`
- eval 时使用 `--api-base http://127.0.0.1:8021` 或 `API_PORT=8021 make eval-retrieval`
- 若要改回 8020，先做环境一致性校验（配置、实例重启、同样本复跑）再决定是否切换基线

### 当前样本覆盖足够与不足的地方

已足够的地方:
- 发现当前 blocker：
  - `3` 条回退样本 + `2` 次 eval 复现，已足够支持“还不能继续”的判断
- 基本 query_type 分布：
  - `exact=19`
  - `semantic=12`
- 基本 granularity 分布：
  - `fine=19`
  - `coarse=12`
- 文档类型基础覆盖：
  - 当前样本已覆盖故障码、SOP、WI、技术要求、标准、操作手册等主干类型

明显不足的地方:
- 阈值临界区样本：
  - 当前几乎没有 `primary_top1_score` 落在 `0.45-0.75` 的样本
  - 也几乎没有 `primary_avg_top_n_score` 落在 `0.35-0.65` 的样本
  - 因此当前 `top1_threshold / avg_top_n_threshold` 仍是 provisional，不能宣称已经“校准完成”
- lexical 边界样本：
  - 当前缺少“本部门 lexical 有少量返回，但质量不足”的中间态样本
  - 现象更偏向两端：要么 department hybrid 命中很多，要么 `global_mode=qdrant`
- `hybrid -> qdrant` 边界样本：
  - 当前回退样本中已出现 `global_mode=qdrant` / `sup_lexical_count=0` 的边界态
  - 但这类样本数量不足，仍不能判断是偶发问题还是系统性脆弱点
- cross-dept 样本结构多样性：
  - 当前 requester 视角主要集中在 `after_sales / assembly / digitalization`
  - 回退样本又偏集中在 `digitalization` 与 `assembly`
  - 还缺少更多部门视角和更多独立 cross-dept query

如果 baseline 恢复后要补样本，优先补:
1. 阈值临界区样本：
   - 让 `primary_top1_score` / `primary_avg_top_n_score` 真正落到当前 provisional threshold 附近
2. lexical 边界样本：
   - 构造“dept lexical 有 2-8 条返回，但仍应触发 supplemental”的中间态
3. `hybrid -> qdrant` 降级样本：
   - 专门覆盖 global lexical 缺失、`sup_lexical_count=0` 的边界情况
4. 独立 cross-dept query：
   - 不要只补和现有 non-cross 高相似的改写样本
5. 非 SOP / WI 型 cross-dept 文档：
   - 增加 FAQ、手册、规范说明类的跨部门引用样本

---

## 4. 当前已确认问题 / 已收口问题

### 4.1 cross-dept supplemental trigger / top-k blocker 已收口（31 条基线）

当前 31 条 fresh baseline 中:
- `supplemental_expected=true` 的 `12` 条样本全部正确触发 supplemental
- `supplemental_expected=true` 的 `12` 条样本 `top1_accuracy = 1.0`
- `supplemental_expected=true` 的 `12` 条样本 `topk_recall = 1.0`
- `supplemental_expected=false` 的 `19` 条样本未出现保守误触发

本轮最小代码修复:
- 在 `backend/app/services/retrieval_service.py` 中新增 exact / fine query 的 top1 literal coverage 低质量保护
- 当 department hybrid top1 的 lexical score 看似”够高”，但 query literal coverage 明显不足时，仍走 `department_low_quality -> supplemental`
- 不扩稳定主契约，不改 chunk / router / rerank

**注意**: 43 条 gate 复核 eval 暴露了上述保护的盲区（cross-013 和 sop-005），详见 §3 gate 复核 eval 报告。

### 4.2 当前剩余差异不再是本轮 blocker

当前 `eval/results/eval_20260406_081609.json` 中唯一仍非 `top1=1.0` 的样本是:
- `sop-001`
- 该样本 `topk_recall=1.0`
- 且在 `eval/results/eval_20260405_134848.json` 中同样不是 top1

因此:
- 这不是本轮 cross-dept supplemental blocker 的新回退
- 当前主 blocker 已从“cross-dept top-k / supplemental 退化”切回“是否已经达到 readiness / gate 要求”

### 4.3 运行基线：Docker 容器占用 8020 端口

**已确认的现象**:
- `localhost:8020` 被 Docker 容器 `enterprise-rag-api` 占用
- `docker inspect` 显示容器 bind 挂载当前工作区(`/home/reggie/vscode_folder/Enterprise-grade_RAG:/app`)并使用 `--reload`
- 同一工作区代码在 fresh `127.0.0.1:8021` 上两次独立运行 eval 结果一致：
  - `eval/results/eval_20260406_081609.json`
  - `eval/results/eval_20260406_082413.json`

**当前结论**:
- 当前 gate 复核基线固定使用 `127.0.0.1:8021`（已稳定复现）
- 在未做环境一致性校验前，不混用 `8020` 与 `8021` 结果
- 如需恢复 8020 为默认基线，先重启/校验容器并在同样本下复跑对比

---

## 5. 当前最小下一步

**gate 复核已完成，结论：GATE NOT PASSED**

当前已发现的具体问题：
1. `cross-013` — department_sufficient 在高置信度语义重叠时误判，supplemental 未触发
2. `sop-005` — fine_query_avg_top_n_threshold 对非确定性向量搜索过于敏感，边界 case 振荡

如果继续做 `Phase 1B-B`, 默认下一步是:

1. **[已完成]** 固化运行基线
   - 确认事实：`8020` 默认命中 Docker 容器实例，`8021` 是 fresh local uvicorn，二者是不同运行实例
   - 基线已可复现：两次独立运行结果一致（`eval_20260406_081609` / `eval_20260406_082413`）
2. **[已完成]** Phase 2B readiness / sample gate 复核
   - gate 复核 eval：`eval/results/eval_20260406_100642.json`
   - 12 条新边界样本已验证（11 通过 / 1 失败）
   - 1 条原始样本出现不稳定行为（sop-005）
   - **结论：GATE NOT PASSED**
3. **[下一步建议]** 解决 gate 复核暴露的 2 个问题
   - `cross-013`: 需要在 department_sufficient 判定中增加语义匹配验证（不能仅依赖 score 阈值）
   - `sop-005`: 需要调整 fine_query_avg_top_n_threshold 或增加振荡容忍机制
   - 解决后需要重跑 43 条样本验证
4. **[禁止]**
   - 在未做环境一致性校验前，把 `8020` 与 `8021` 结果混用为同一基线
   - 在 gate 未通过的情况下进入 `Phase 2B` 正式实现
   - 修改样本定义来掩盖问题

---

## 6. 当前禁止动作

在 `Phase 1B-B` gate 未明确前, 默认不要做:
- 把 fresh API 的恢复结果直接等同于“readiness 已完成”
- 未经 gate 复核就正式开始 `Phase 2B` chunk 实现
- 调 router / hybrid 权重作为主路径
- 先动 rerank 来掩盖 retrieval 问题
- 改 stable contract
- 把当前 provisional 阈值写成 final recommendation
- 修改 `retrieval_samples.yaml` 来人为解决环境问题
- 为了让指标好看而改规则定义
- 把怀疑写成已确认的根因

---

## 7. 使用方式

当任务与 retrieval 优化相关时:

1. 先读本文件,确认当前阶段和最新 baseline
2. 再读:
   - `MAIN_CONTRACT_MATRIX.md`
   - `RETRIEVAL_OPTIMIZATION_PLAN.md`
   - `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
   - `eval/README.md`
   - `scripts/eval_retrieval.py`
   - `eval/results/` 最新结果
3. 再决定本轮属于
   - `baseline`
   - `supplemental`
   - `chunk`
   - `router`
   - `rerank`

如果本文件与上述 source of truth 冲突, 以上述 source of truth 为准,并优先更新本文件。

在以下任一情况发生后, 默认把"更新本文件"视为收尾动作的一部分:
- baseline 报告路径变化
- supplemental / chunk 相关阈值变化
- 当前阶段从 `baseline / supplemental / chunk / router / rerank` 任一层切换
- blocker 结论变化
- `可以进入下一阶段 / 还不能进入下一阶段` 的判断变化
