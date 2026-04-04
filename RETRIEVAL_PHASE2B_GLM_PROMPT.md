# Retrieval Phase 2B GLM Prompt

## 这一阶段现在能做什么

当前**还不能正式开始 `Phase 2B` 的 chunk 优化实现**。

这个文件在当前仓库状态下，只应用于：

- `2B readiness audit`
- `structured chunk hotspot review`
- `chunk 优化前置证据梳理`

**不要**把它当成“现在就可以直接改 `structured_chunker.py` / `text_chunker.py` 并开始调 chunk”的开工指令。

---

## 当前状态

截至当前仓库状态：

- `Phase 2A / Gate` 的 runbook、baseline 入口、重建编排脚手架已经基本补齐
- 但 `Phase 1B-B` 仍未正式闭环
- 最新 retrieval eval 里，`supplemental_precision` 仍为 `null`
- 最新 retrieval eval 里，`supplemental_recall` 仍为 `0.0`
- `conservative_trigger_count` 仍为 `0`

这意味着：

- `2A gate` 大体具备
- 但**还没有满足正式进入 `2B` 的业务前置条件**

计划文档中的顺序约束仍然成立：

- `chunk` 优化应排在 `supplemental 阈值收口之后`
- 只有在“命中文档大体对、supplemental 触发也大体合理，但 top chunk / citation 仍明显不对”时，chunk 才能升级为下一阶段第一优先级

所以当前阶段的正确目标是：

- 审核 `structured_chunker` / `text_chunker` 的潜在热点
- 准备未来 `2B` 可能需要的测试和评估思路
- 但**不正式落地 chunk 行为改动**

---

## 当前已核实的热点

下面这些点已经有仓库代码或 eval 结果支撑，可以作为本轮 readiness audit 的起点：

1. `section_summary` 很可能在抢 `clause` query
   - 当前 `section_summary` 会把分组内的 clause 内容直接拼进 summary 文本
   - `retrieval_text` 又会把整段 summary content 原样带入检索文本
   - 最新 SOP / fine-grained 样本里，很多 `expected=clause` 的 case，heuristic `actual` 都落在 `section_summary`

2. `Step` 风格条目识别缺失
   - 当前 `_CLAUSE_PATTERN` 只识别 `X.Y` 形式
   - `Step1 / Step2 / Step3` 这类结构目前不在显式 clause 识别范围内

3. `clause` 信号不够强，但不要把原因说成只有 `clause_no_normalized`
   - 现在 `clause_no` 已经会通过 `section` 和 `keywords` 间接进入 `retrieval_text`
   - 更准确的说法是：`clause` 级别的识别信号还不够强，但首要问题仍然是 `section_summary` 覆盖了子 clause 内容
   - 因此不要把问题简单归因为“`clause_no_normalized` 没进 retrieval_text”

---

## 硬约束

- 不改主契约
- 不改变现有稳定字段名
- 不把这轮写成“Phase 2B started”或“chunk optimization completed”
- 不直接修改默认 chunk 参数
- 不直接修改 `structured_chunker.py` / `text_chunker.py` 的行为逻辑
- 不直接做真实 reindex / rebuild
- 不做“重写整套 chunk 框架”
- 如果没有样本和评估证据，不要假设某个 chunk 方向一定有效

---

## 开工前必须先读

- [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)
- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [OPS_CHUNK_REBUILD_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_CHUNK_REBUILD_RUNBOOK.md)
- [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md)
- [eval/retrieval_samples.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/retrieval_samples.yaml)
- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)
- `eval/results/` 最新结果

---

## 当前这轮允许的交付物

### 1. readiness audit

允许输出：

- `structured_chunker` 的热点分析
- clause / section_summary / doc_summary 的潜在抢召回问题
- `retrieval_text` 组成问题的证据化梳理
- 如果未来要做 `2B`，最值得优先改的 1-3 个点

### 2. 测试和评估准备

允许输出：

- 建议新增：
  - `backend/tests/test_structured_chunker.py`
- 建议增强：
  - `backend/tests/test_document_ingestion.py`
- 未来如何做 before / after 评估
- 未来如何确认 clause query 是否被 summary 抢走

### 3. 不允许的内容

当前不要做：

- 直接改 `structured_chunker.py`
- 直接改 `text_chunker.py`
- 直接改默认 chunk 参数
- 直接执行 `2B` 的 chunk 参数扫描
- 直接宣称“现在可以进入 chunk 优化实现”

---

## 这轮验收标准

这轮如果做得好，应该得到的是：

- 一个清楚的 `2B readiness audit`
- 一个结构化 chunk 风险/热点列表
- 一个未来真正进入 `2B` 时可执行的最小切入点

而**不是**：

- 实际的 chunk 行为改动
- 实际的 chunk 参数调优结果
- “2B 已开始/已完成”的结论

---

## 可直接发给 GLM 的 Prompt

```text
基于当前仓库状态，继续 Retrieval Phase 2，但这轮不是正式开始 `2B` 实现，而是做 `2B readiness audit`。

请先阅读：
- MAIN_CONTRACT_MATRIX.md
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- OPS_CHUNK_REBUILD_RUNBOOK.md
- eval/README.md
- eval/retrieval_samples.yaml
- backend/app/rag/chunkers/structured_chunker.py
- backend/app/rag/chunkers/text_chunker.py
- backend/app/services/ingestion_service.py
- backend/tests/test_document_ingestion.py
- eval/results/ 最新结果

当前状态很重要：

- `Phase 2A / Gate` 已基本具备
- 但 `Phase 1B-B` 仍未正式闭环
- 最新 eval 中：
  - `supplemental_precision = null`
  - `supplemental_recall = 0.0`
  - `conservative_trigger_count = 0`
- 因此现在还不能正式进入 `2B` 的 chunk 优化实现阶段

任务：
做一次 `Phase 2B readiness audit`。目标不是改 chunk 逻辑，而是判断：
1. 如果未来允许进入 `2B`，最值得先动的 structured chunk 热点是什么
2. 当前 `structured_chunker` / `text_chunker` 的哪几个点最可能影响 top chunk / citation 质量
3. 未来真正进入 `2B` 前，还缺哪些证据、测试或评估入口

当前已知热点可作为起点，但必须自己复核，不要直接照抄成结论：
1. `section_summary` 可能抢 `clause`
2. `_CLAUSE_PATTERN` 不识别 `Step1/2/3`
3. `clause` 信号偏弱，但不要把原因简单写成“`clause_no_normalized` 缺失”

必须遵守：
1. 不改 retrieval/search、chat/ask 的主契约。
2. 不改变现有稳定字段名和 chunk_type 基本语义。
3. 这轮不要直接修改 `structured_chunker.py` / `text_chunker.py` 的行为逻辑。
4. 不要直接修改 generic text 默认 chunk 参数。
5. 不要做真实 reindex / rebuild。
6. 不要把这轮写成 “Phase 2B started/completed”。

请优先完成：
1. 审查 structured chunk 的 `retrieval_text / doc_summary / section_summary / clause` 平衡
2. 判断 clause query 是否可能被 section_summary / doc_summary 抢走
3. 梳理文号 / 章节号 / 条款号 / 关键词是否充分进入 retrieval_text
4. 明确区分：
   - 已被代码或 eval 直接支持的问题
   - 合理怀疑但还需要更多证据的问题
5. 给出未来真正进入 `2B` 时，优先级最高的 1-3 个最小改动候选
6. 给出未来应补的测试与评估建议，优先考虑：
   - `backend/tests/test_structured_chunker.py`
   - `backend/tests/test_document_ingestion.py`

不要做的事：
- 不要直接改 chunk 行为
- 不要直接改默认 chunk 参数
- 不要假设 1B-B 已经闭环
- 不要把 readiness audit 写成实现完成
- 不要大规模重构 ingestion / chunk framework

完成后请输出：
1. 修改文件列表
2. 你确认到的当前 `2B readiness` 状态
3. 结构化 chunk 的主要热点 / 风险点
4. 未来真正进入 `2B` 时最值得优先改的 1-3 个点
5. 建议补的测试与评估入口
6. 当前为什么还不能正式进入 `2B`
7. 这轮是否只是 audit / readiness，而不是实现
8. 哪些 hotspot 已经有证据，哪些还只是合理怀疑
```
