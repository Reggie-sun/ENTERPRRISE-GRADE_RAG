# Retrieval Evaluation — 样本字段与评分规则

## 快速开始

```bash
# 使用默认 demo 账号运行评估
make eval-retrieval

# 或直接运行脚本
python scripts/eval_retrieval.py

# 覆盖账号密码（支持环境变量）
AUTH_USERNAME=your_user AUTH_PASSWORD=your_pass make eval-retrieval
python scripts/eval_retrieval.py --username your_user --password your_pass
```

**默认账号**：`sys.admin.demo` / `sys-admin-demo-pass`（与 `LOCAL_DEV_RUNBOOK.md` 一致）

---

## 重要限制说明

### 部门评估边界

**当前 `requester_department_id` 只是样本标签，不是真实的权限模拟。**

- `by_department` 分组是基于样本标签的分组，**不等于真实权限视角**
- `cross-dept supplemental` 的结果应标记为 **provisional**（暂定）
- 如需真实部门权限评估，需要实现完整的 auth profile 映射系统

### chunk_type 评分是启发式推断

**`heuristic_chunk_type_score` 是从以下字段推断的，不是 ground-truth：**

- `retrieval_strategy`
- `source_scope`
- 文本长度

不要将其作为正式评估指标使用。

### baseline_config_snapshot.yaml 是模板

该文件中的值部分为手工填写，部分为 TBD 占位符。它记录检索评估基准配置的**预期结构**，并非从运行时自动导出的真实快照。

---

## 样本字段说明

每条样本包含以下字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 样本唯一标识，格式：`{type}-{seq}` |
| `query` | string | 是 | 用户输入的检索查询 |
| `query_type` | enum | 是 | `exact` / `semantic`，标记查询分类 |
| `expected_granularity` | enum | 是 | `fine` / `coarse`，期望命中粒度 |
| `expected_doc_ids` | string[] | 是 | 期望命中的文档 ID 列表。首个为首选文档 |
| `expected_chunk_type` | enum | 是 | `clause` / `section_summary` / `doc_summary` |
| `expected_terms` | string[] | 否 | 期望结果中出现的关键术语 |
| `supplemental_expected` | bool | 是 | 该样本是否应该触发跨部门补充召回 |
| `requester_department_id` | string | 是 | 模拟请求者所属部门 ID |
| `status` | enum | 否 | `draft` / `verified`，标记样本成熟度 |
| `source` | enum | 否 | `synthetic` / `real`，标记样本来源 |
| `note` | string | 否 | 样本说明 |

### 样本分类

| 分类 | query_type | expected_granularity | 典型场景 |
|------|-----------|---------------------|---------|
| exact / code-like | exact | fine | 故障码、文号、条款号 |
| fine-grained clause | exact | fine | 具体判定标准、操作要求 |
| semantic explanation | semantic | coarse | 概念解释、原因分析 |
| broad summary | semantic | coarse | 概览、清单、体系结构 |
| cross-dept supplemental | semantic | coarse | 需要跨部门补充召回 |

---

## 评分规则

### 1. top1_accuracy

**定义：** top1 结果的 `document_id` 必须严格等于 `expected_doc_ids[0]`（首选文档）才算全对。

| 条件 | 计分 |
|------|------|
| top1 的 `document_id` == `expected_doc_ids[0]` | 命中（1 分） |
| top1 的 `document_id` in `expected_doc_ids` 但不等于首选 | 不计入 top1_accuracy |

### 2. top1_partial_hit

**定义：** top1 结果命中了 `expected_doc_ids` 中的文档，但不是首选文档。

| 条件 | 计分 |
|------|------|
| top1 的 `document_id` in `expected_doc_ids` 且 != `expected_doc_ids[0]` | 半对（0.5 分） |
| top1 的 `document_id` 不在 `expected_doc_ids` 中 | 不计入 |

**重要：** `top1_partial_hit` 单独统计，不并入 `top1_accuracy`。

### 3. topk_recall

**定义：** top-k 结果中是否至少有一个 `document_id` 在 `expected_doc_ids` 里。

| 条件 | 计分 |
|------|------|
| top-k 中任意一条结果的 `document_id` in `expected_doc_ids` | 召回成功（1 分） |
| top-k 中没有任何结果命中 | 召回失败（0 分） |

### 4. expected_doc_coverage

**定义：** 当 `expected_doc_ids` 有多个时，衡量 top-k 覆盖了多少期望文档。

计算公式：
```
expected_doc_coverage = len(hit_docs ∩ expected_doc_ids) / len(expected_doc_ids)
```

其中 `hit_docs` 是 top-k 结果中出现过的所有 `document_id` 集合。

### 5. chunk_type 命中（heuristic / 启发式）

> ⚠️ **注意**：此指标是从 `retrieval_strategy`、`source_scope`、文本长度推断的，**不是 ground-truth**。
> 不要将其作为正式评估指标使用。报告中以 `heuristic_chunk_type_score` 命名。

**定义：** top1 结果的 chunk 类型是否匹配期望。

| expected_chunk_type | 实际命中 | 判定 |
|---------------------|---------|------|
| clause | clause | 全对 |
| clause | section_summary | 半对 |
| clause | doc_summary | 错 |
| section_summary | section_summary | 全对 |
| section_summary | doc_summary | 半对 |
| doc_summary | doc_summary | 全对 |

### 6. supplemental_precision / supplemental_recall

**定义：** 补充召回触发的准确率和召回率。

| 指标 | 计算方式 |
|------|---------|
| `supplemental_precision` | `supplemental_expected=true` 且实际触发的样本数 / 实际触发的总样本数 |
| `supplemental_recall` | `supplemental_expected=true` 且实际触发的样本数 / `supplemental_expected=true` 的总样本数 |

判对规则：

| supplemental_expected | 实际触发 | 判定 |
|----------------------|---------|------|
| true | 触发 | 正确（TP） |
| true | 未触发 | 漏触发（FN） |
| false | 未触发 | 正确（TN） |
| false | 触发 | 保守触发（单独计数） |

### 7. conservative_trigger_count

**定义：** `supplemental_expected=false` 但实际触发的样本数。

**特殊处理：** 保守触发不直接并入误判（FP），而是单独记录。只有在满足以下任一条件时才计为误判：
- 触发 supplemental 后 top-k 结果质量明显下降（噪声增加）
- 触发 supplemental 后 top1 从正确变为错误

否则仅记录为"保守触发"，不惩罚。

### 8. 汇总指标

| 指标 | 计算方式 |
|------|---------|
| `top1_accuracy` | top1 全对样本数 / 总样本数 |
| `top1_partial_hit_rate` | top1 半对样本数 / 总样本数 |
| `topk_recall` | top-k 召回成功样本数 / 总样本数 |
| `expected_doc_coverage_avg` | 所有样本的 doc_coverage 平均值 |
| `supplemental_precision` | TP / (TP + conservative) |
| `supplemental_recall` | TP / (TP + FN) |
| `conservative_trigger_count` | 保守触发样本数 |

### 9. 分组统计

除全局汇总外，脚本还输出以下分组维度：

- `by_query_type`: 按 `exact` / `semantic` 分组
- `by_department`: 按 `requester_department_id` 分组（⚠️ **仅基于样本标签，不是真实权限模拟**）
- `by_granularity`: 按 `expected_granularity` 分组
- `by_supplemental_expected`: 按是否期望触发 supplemental 分组

> **注意**：`by_department` 和 `cross-dept supplemental` 的结果应视为 provisional，因为当前脚本没有以不同部门身份登录进行检索。
