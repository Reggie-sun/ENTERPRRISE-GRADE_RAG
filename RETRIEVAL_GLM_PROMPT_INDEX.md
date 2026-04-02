# Retrieval GLM Prompt Index

这组文档是给 GLM 用的“分阶段执行包”。

使用方式：

1. 不要一次把所有阶段都丢给 GLM。
2. 按顺序一份一份执行。
3. 每个阶段完成后，先看改动和测试结果，再决定是否进入下一阶段。
4. 任何阶段都必须遵守 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)。

---

## 推荐顺序

1. [RETRIEVAL_PHASE1A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_GLM_PROMPT.md)
2. [RETRIEVAL_PHASE1B_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1B_GLM_PROMPT.md)
3. [RETRIEVAL_PHASE2A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE2A_GLM_PROMPT.md)
4. [RETRIEVAL_PHASE2B_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE2B_GLM_PROMPT.md)
5. [RETRIEVAL_PHASE3_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE3_GLM_PROMPT.md)
6. [RETRIEVAL_PHASE4_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE4_GLM_PROMPT.md)

---

## 每个阶段都要重复强调的硬约束

- 不新增 `retrieval/search`、`chat/ask`、`system-config` 的稳定 public 字段。
- 不改变当前稳定字段语义。
- `retrieval / chat / SOP` 继续共用同一套 retrieval 与 supplemental 判定逻辑。
- 不允许为了提升召回率打穿 tenant / department / retrieval scope 边界。
- 没有样本基线，不进入下一阶段。
- 没有回滚预案，不改 chunk。

---

## 各阶段目标

### Phase 1A

- 建立样本、评分规则、baseline 配置快照和评估脚本基础设施。

### Phase 1B

- 基于内部真源校准 supplemental 阈值，补齐诊断和回归。

### Phase 2A

- 先把 chunk 重建、验证、回滚 runbook 补齐。

### Phase 2B

- 在已有 chunk 体系上做增量优化，优先结构化文档。

### Phase 3

- 扩充 query router 样本，校准 hybrid 权重。

### Phase 4

- 基于 canary 样本复盘 rerank，再决定默认策略。

---

## 建议

- 如果你要 GLM 先做一个最稳的起手式，就先给它 [RETRIEVAL_PHASE1A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_GLM_PROMPT.md)。
- 如果你要 GLM 先做文档和脚手架而不是动检索逻辑，就先给它 Phase 1A 或 Phase 2A。
