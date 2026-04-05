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
- 当前状态：`supplemental 触发校准已收口，但 cross-dept hit quality 仍未收口`
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

- `eval/results/eval_20260405_120952.json`

关键指标：

- `top1_accuracy = 58.06%`
- `topk_recall = 61.29%`
- `expected_doc_coverage_avg = 61.29%`
- `supplemental_precision = 1.0`
- `supplemental_recall = 1.0`
- `conservative_trigger_count = 0`

解释：

- 这说明 supplemental trigger calibration 已经收口
- 但 `supplemental_expected=true` 的 `12` 条样本当前仍然 `topk_recall = 0.0`
- 也就是说，当前不是“1B-B 完成”，只是 trigger blocker 已切换

---

## 4. 当前已确认问题

### 4.1 触发层 false negatives 已清零

最新 baseline 中：

- `supplemental_expected=true` 的 `12` 条样本已全部触发 supplemental
- `supplemental_expected=false` 的 `19` 条样本没有保守误触发

### 4.2 当前主问题不再是 trigger blocker，而是命中质量 blocker

已确认：

- ACL seed 与 auth profile 对这些样本并不缺失
- `department_sufficient / department_low_quality` 的 supplemental 触发现在已经和样本预期对齐
- 但 supplemental 触发后，融合结果 top-k 仍然被本部门候选主导，`expected_doc_ids` 仍然没有进入 top-k

也就是说，当前更像是：

- 触发条件已经修正
- 但 supplemental route 的结果还没有真正改变 cross-dept top-k 命中
- 当前 blocker 已从“trigger 是否触发”切换到“trigger 后为什么仍然 hit 不到期望文档”

### 4.3 当前代表性现象

例如：

- `cross-002`、`cross-012`：已经触发 supplemental，但 top-k 仍然只有 `doc_20260321070337_445684f4`
- `cross-007`、`cross-009`、`cross-010`：已经触发 supplemental，但 top-k 仍被本部门多个错误文档占满
- 所有 `supplemental_expected=true` 样本当前 `topk_recall = 0.0`

---

## 5. 当前最小下一步

如果继续做 `Phase 1B-B`，默认下一步是：

1. 保持当前 supplemental trigger calibration 结果不回退
2. 审计 supplemental 触发后为什么 top-k 仍被 department 候选主导
3. 优先看 `retrieval_service.py` 的 scope 融合 / 截断策略，而不是继续抬触发阈值
4. 复跑 `make eval-retrieval`，重点看 `supplemental_expected=true` 的 `topk_recall`

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
