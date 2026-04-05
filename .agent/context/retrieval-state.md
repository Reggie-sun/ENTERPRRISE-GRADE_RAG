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
> - 可用 `make check-retrieval-state` 做最小检查；如果 baseline / 阈值相关输入已变而本文件没变，检查应失败

更新时间：`2026-04-05`

---

## 1. 当前阶段

- 当前主线：`Phase 1B-B`
- 当前状态：`supplemental 已进入可校准阶段，但仍未 final tuning completed`
- `Phase 2A / Gate`：已完成
- `Phase 2B`：只允许 `readiness / audit`，**不允许**正式实现
- `Phase 3`：未开始

---

## 2. 当前硬约束

- 不扩稳定主契约，先看 `MAIN_CONTRACT_MATRIX.md`
- `retrieval / chat / SOP` 继续共用同一套 supplemental 判定逻辑
- retrieval 优化顺序必须保持：
  1. `baseline / supplemental`
  2. `chunk`
  3. `router / hybrid`
  4. `rerank`
- 不要把 heuristic 字段当 ground truth
- 不要为了让指标变好看而篡改 verified baseline 语义

---

## 3. 当前 baseline

### 样本状态

- `eval/retrieval_samples.yaml`：
  - `31` 条 verified 样本
  - 其中 `12` 条 `supplemental_expected=true`

### 运行前置条件

- auth profile 映射已就位：
  - `eval/retrieval_auth_profiles.yaml`
- eval ACL seed 已就位：
  - `eval/retrieval_document_acl_seed.yaml`
  - `scripts/seed_retrieval_eval_acl.py`
- PostgreSQL metadata 场景已验证可写入 ACL seed
- eval 已能使用真实部门 token 跑，不再只是 `sys_admin` 视角

### 当前 provisional 阈值

当前运行时保留值：

- `top1_threshold = 0.55`
- `avg_top_n_threshold = 0.45`
- `fine_query_top1_threshold = 0.95`
- `fine_query_avg_top_n_threshold = 0.70`

这是 **provisional**，不是 final recommendation。

### 最新 baseline 报告

- `eval/results/eval_20260405_112755.json`

关键指标：

- `top1_accuracy = 58.06%`
- `topk_recall = 61.29%`
- `expected_doc_coverage_avg = 61.29%`
- `supplemental_precision = 1.0`
- `supplemental_recall = 0.5`
- `conservative_trigger_count = 0`

解释：

- 这说明 supplemental 指标已经进入“可校准”状态
- 但 cross-dept 命中质量仍未稳定，当前不是“1B-B 完成”

---

## 4. 当前已确认问题

### 4.1 仍有 6 条 cross false negatives

最新 baseline 中仍未触发 supplemental 的样本：

- `cross-002`
- `cross-006`
- `cross-007`
- `cross-009`
- `cross-010`
- `cross-012`

### 4.2 当前主问题不是 ACL 缺失，而是 sufficiency 判定

已确认：

- ACL seed 与 auth profile 对这些样本并不缺失
- 这些 case 大多被判成 `department_sufficient`
- 但至少在 `cross-002`、`cross-009` 中，`department_effective_count` 是被同一篇错误文档的多个 chunk 撑满的

也就是说，当前更像是：

- `department_effective_count` 统计 chunk 数，而不是唯一文档数
- “少数本部门错误文档的重复 chunk”会把 primary recall 误判成 sufficient

### 4.3 还有 query granularity 偏差

至少 `cross-007` 当前没有走到 fine-query 更严格阈值，说明：

- 某些 query 的 `query_granularity` 还会影响 trigger 行为
- 这不是单纯继续抬阈值就能解决的

---

## 5. 当前最小下一步

如果继续做 `Phase 1B-B`，默认下一步是：

1. 修 `retrieval_service.py` 的 supplemental sufficiency 判定
   - 至少评估“唯一文档数”而不只是 chunk 数
2. 补 `test_retrieval_chat.py` 回归
   - 覆盖“同一篇错误文档多个 chunk 不能把 department 判成 sufficient”
3. 复跑 `make eval-retrieval`
4. 再看剩余 false negatives 是否需要继续调阈值

---

## 6. 当前禁止动作

在 `Phase 1B-B` 没收口前，默认不要做：

- 正式开始 `Phase 2B` chunk 实现
- 调 router / hybrid 权重作为主路径
- 先动 rerank 来掩盖 retrieval 问题
- 改 stable contract
- 把当前 provisional 阈值写成 final recommendation

---

## 7. 使用方式

当任务与 retrieval 优化相关时：

1. 先读本文件，确认当前阶段和最新 baseline
2. 再读：
   - `MAIN_CONTRACT_MATRIX.md`
   - `RETRIEVAL_OPTIMIZATION_PLAN.md`
   - `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
   - `eval/README.md`
   - `scripts/eval_retrieval.py`
   - `eval/results/` 最新结果
3. 再决定本轮属于：
   - `baseline`
   - `supplemental`
   - `chunk`
   - `router`
   - `rerank`

如果本文件与上述 source of truth 冲突，以上述 source of truth 为准，并优先更新本文件。

在以下任一情况发生后，默认把“更新本文件”视为收尾动作的一部分：

- baseline 报告路径变化
- supplemental / chunk 相关阈值变化
- 当前阶段从 `baseline / supplemental / chunk / router / rerank` 任一层切换
- blocker 结论变化
- `可以进入下一阶段 / 还不能进入下一阶段` 的判断变化
