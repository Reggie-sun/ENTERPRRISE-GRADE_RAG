# Retrieval Phase 2B GLM Prompt

## 这一阶段做什么

在 Phase 2A 之后，开始真正优化 chunk。

优先顺序：

1. 先校准现有 `SOPStructuredChunker`
2. 再决定是否需要动 generic text 参数
3. 不要先做大规模架构重写

---

## 硬约束

- 不改主契约
- 不改变现有稳定字段名
- 优先做增量优化，不做“重写整套 chunk 框架”
- 如果没有样本证明收益，不要随意改默认 chunk 参数

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)

---

## 交付物要求

### 1. 结构化 chunk 优先

优先检查并优化：

- `retrieval_text`
- `doc_summary / section_summary / clause` 的平衡
- 文号、章节号、关键词是否充分进入检索文本
- clause 问句是否容易被 summary 抢走

### 2. 测试

建议新增：

- `backend/tests/test_structured_chunker.py`

并补充或增强：

- `backend/tests/test_document_ingestion.py`

### 3. generic text

如果需要做 generic text 参数扫描：

- 先做评估脚手架
- 没有样本证据前，不要轻易改默认参数

### 4. 文档类型路由

可以做最小版设计，但只能作为“轻量可扩展点”，不要上来搞大重构。

---

## 验收标准

- 条款/文号类 query 更容易命中 clause
- citation 更聚焦
- 不明显增加误召回
- ingestion 主流程不被打坏

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- backend/app/rag/chunkers/structured_chunker.py
- backend/app/rag/chunkers/text_chunker.py
- backend/app/services/ingestion_service.py
- backend/tests/test_document_ingestion.py

任务：实现 Retrieval Phase 2B。目标是在现有 chunk 体系上做增量优化，优先处理结构化文档，提升 top chunk 和 citation 质量。

必须遵守：
1. 不改 retrieval/search、chat/ask 的主契约。
2. 不改变现有稳定字段名和 chunk_type 基本语义。
3. 优先校准现有 SOPStructuredChunker，不做大规模重写。
4. 如果没有样本证据，不要贸然修改 generic text 默认 chunk 参数。

请优先完成：
1. 审查并优化 structured_chunker.py 中 retrieval_text / doc_summary / section_summary / clause 的平衡
2. 补充结构化 chunk 的测试，优先新增 test_structured_chunker.py
3. 必要时补 ingestion 相关测试
4. 如果合适，再增加一个很薄的 generic chunk 参数评估入口，但不要先改默认值

重点观察：
- 文号/章节号/条款号是否进入 retrieval_text
- clause query 是否被 section_summary 或 doc_summary 抢走
- citation 是否比之前更短、更聚焦

不要做的事：
- 不要先搞“全新 chunk engine”
- 不要大规模抽象到影响 ingestion 主流程稳定性
- 不要在没有证据时修改一堆默认参数

完成后请输出：
1. 修改文件列表
2. 你优先改了哪些结构化命中问题
3. 测试命令与结果
4. 哪些 generic chunk 优化仍只适合保留在后续阶段
```
