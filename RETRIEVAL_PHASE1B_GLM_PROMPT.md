# Retrieval Phase 1B GLM Prompt

## 这一阶段做什么

在 Phase 1A 基础上，开始真正校准 supplemental 阈值，但仍然不扩主契约。

重点是：

- 使用内部真源 `_internal_retrieval_controls`
- 用固定样本比较多组阈值
- 让 diagnostics 和实际判定一致
- 补齐关键回归测试

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
- [system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/system_config_service.py)
- [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- [test_retrieval_chat.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_retrieval_chat.py)
- [test_system_config_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_system_config_service.py)

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

---

## 验收标准

- 主契约测试继续通过
- retrieval/chat/SOP 行为保持一致
- diagnostics 能反映真实阈值和触发依据
- 没有扩 public contract

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读以下文件：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- MAIN_CONTRACT_MATRIX.md
- backend/app/services/system_config_service.py
- backend/app/services/retrieval_service.py
- backend/tests/test_retrieval_chat.py
- backend/tests/test_system_config_service.py
- backend/tests/test_system_config_endpoints.py

任务：实现 Retrieval Phase 1B。目标是基于内部真源校准 supplemental 阈值，并补齐 diagnostics / regression，但不能扩 public contract。

必须遵守：
1. 不新增公开 system-config 字段。
2. 不把 _internal_retrieval_controls 暴露到 public response。
3. retrieval / chat / SOP 必须继续共用同一套 supplemental 判定逻辑。
4. 优先在现有脚本基础上增量实现，不要新造过重框架。

请完成以下工作：
1. 为样本评估增加多组阈值实验能力
2. 产出实验结果记录模板或结果文件
3. 校验并增强 retrieval diagnostics 的一致性
4. 补齐关键回归测试，重点覆盖：
   - department_sufficient
   - department_low_quality
   - department_insufficient
   - fine query stricter thresholds
   - truncate_to_top_k True/False

诊断面重点关注字段：
- primary_threshold
- primary_top1_score
- primary_avg_top_n_score
- quality_top1_threshold
- quality_avg_threshold
- supplemental_triggered
- supplemental_trigger_basis

不要做的事：
- 不扩 API 主字段
- 不改 MAIN_CONTRACT_MATRIX 约束
- 不新增一套 endpoint 级分叉规则

完成后请输出：
1. 修改文件列表
2. 采用的实验方案
3. 运行的测试命令与结果
4. 推荐继续使用的默认阈值或下一步实验建议
```
