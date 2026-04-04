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

# 查看 1B-B ACL seed 计划（默认 dry-run，本地 JSON 方案会同时预演缺失 stub 的创建）
python scripts/seed_retrieval_eval_acl.py --create-missing-local-json

# 将 ACL seed 应用到本地 JSON metadata（缺失记录可从 uploads 自动补 stub）
python scripts/seed_retrieval_eval_acl.py --apply-local-json --create-missing-local-json

# 将 ACL seed 应用到 PostgreSQL metadata store
python scripts/seed_retrieval_eval_acl.py --apply-postgres
```

**默认账号**：`sys.admin.demo` / `sys-admin-demo-pass`（与 `LOCAL_DEV_RUNBOOK.md` 一致）

---

## 重要限制说明

### 部门评估前置条件（当前状态 2026-04-04）

**当前 `requester_department_id` 仍然是样本逻辑标签，但仓库内已经补齐了两层内部桥接：**

1. **真实 auth profile 映射**：`eval/retrieval_auth_profiles.yaml` 将
   - `dept_after_sales` → `dept_installation_service`
   - `dept_assembly` → `dept_production_technology`
   - `dept_digitalization` → `dept_digitalization`

   并映射到真实可登录 demo 账号。`scripts/eval_retrieval.py` 会优先用这些账号发起检索请求，因此部门视角来自真实 `auth_context` / token，而不是 request body。

2. **eval ACL seed**：`eval/retrieval_document_acl_seed.yaml` + `scripts/seed_retrieval_eval_acl.py` 提供了一套可控的 metadata seed，用于把 cross-dept 样本涉及文档的
   - `department_id`
   - `department_ids`
   - `retrieval_department_ids`
   - `visibility`

   补到运行中的 metadata store（本地 JSON 或 PostgreSQL）。

**这意味着 1B-B 的仓库内前置条件已经补齐，但 supplemental 指标是否真的可校准，仍取决于你是否把 ACL seed 应用到了正在运行的 metadata store。**

当前判断线如下：

- **auth 侧已接通**：`scripts/eval_retrieval.py` 可按样本逻辑部门切换到真实的部门级 demo 身份。
- **metadata 侧已有 seed**：仓库里已经有 cross-dept 相关文档的部门归属与检索补充授权配置。
- **仍需环境执行**：如果运行中的 API 还在读未 seed 的 metadata，`supplemental_precision / recall` 仍然会继续失真。

因此推荐顺序是：

1. 先运行 `python scripts/seed_retrieval_eval_acl.py --create-missing-local-json` 做 dry-run。
2. 再按你的 metadata 后端选择：
   - `--apply-local-json --create-missing-local-json`
   - 或 `--apply-postgres --dry-run` / `--apply-postgres`
3. 然后重新运行 `make eval-retrieval`。

### 仍然存在的限制

- `requester_department_id` 仍是逻辑样本标签，不会变成 API 稳定字段。
- `RetrievalRequest` 仍然**没有** `department_id` 字段；真实部门视角只来自登录后的 `auth_context` / token。
- 如果当前 API 没启动、或 active metadata store 还没应用 ACL seed，supplemental 指标仍然不能当最终校准结果使用。
- `backend/tests/test_retrieval_diagnostics.py` 当前仍是 **4 failed, 6 passed**，这组测试还不能当作 1B-B 回归验证闭环。

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

> **注意**：`by_department` 仍是逻辑标签分组；当 auth profile mapping 生效时，报告中还会额外输出 `by_auth_department`（真实 token 部门）分组。

### 10. 跨部门补充召回样本（supplemental_expected=true）

当前样本集包含 `supplemental_expected: true` 的样本（cross-001 至 cross-012），用于测试跨部门补充召回场景。

**验证边界说明：**

- **文档命中层面已验证**：每条样本的 `query → expected_doc_ids` 映射已通过 live retrieval 调用确认正确。
- **部门权限层面已有仓库内 bridge**：当前评估脚本可通过 `eval/retrieval_auth_profiles.yaml` 使用真实部门级 demo 身份登录。
- **supplemental 触发判定仍依赖 metadata seed**：标记 `supplemental_expected: true` 仍然是基于文档内容与部门归属的逻辑判断；要让它变成可校准指标，运行中的 metadata store 必须先应用 `eval/retrieval_document_acl_seed.yaml`。
- **真实闭环条件**：auth profile mapping + ACL seed 都生效后，才能验证 supplemental 是否真正在正确时机触发。

这意味着：
- 当前评估仍然可以报告这些样本的 top1 命中率和 topk recall
- supplemental precision/recall 只有在 active metadata store 已 seed 时才有意义
- 当前阶段这些样本既用于记录预期行为，也用于 1B-B 的 auth / metadata 闭环验证
