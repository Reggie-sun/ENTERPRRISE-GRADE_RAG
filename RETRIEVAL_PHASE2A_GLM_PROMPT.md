# Retrieval Phase 2A GLM Prompt

## 这一阶段做什么

在改 chunk 之前，先把“怎么重建、怎么验证、怎么回滚”写清楚。

这是一个 gate 阶段，不是直接改 chunk 逻辑。

**注意：当前只能开始 `Phase 2A / Gate`，不能进入 `Phase 2B`。**

- `2A`：补齐 chunk 重建、验证、回滚 runbook 与命令入口
- `2B`：真正开始 chunk 参数优化或结构化 chunk 规则优化

当前仓库状态下：

- `Phase 1A / 1B-A` 已完成，verified baseline 已建立
- `1B-B` 仍未正式闭环，但这**不阻止**先做 `2A` 的 gate 准备
- 这轮工作的目标是“把 chunk 改动前置条件补齐”，**不是**开始调 `chunk_size_chars`、`chunk_overlap_chars`、`chunk_min_chars`

---

## 硬约束

- 没有回滚预案，不进入 chunk 改动
- 没有样本验证路径，不进入 chunk 改动
- 如果仓库当前没有足够安全的自动化条件，优先写 runbook，不要硬造高风险 destructive script
- 不直接改 `text_chunker.py` / `structured_chunker.py` 的行为逻辑
- 不直接修改默认 chunk 参数
- 不把这轮写成 “Phase 2 chunk optimization completed”
- 不扩稳定主契约

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [eval/README.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/README.md)
- [eval/retrieval_samples.yaml](/home/reggie/vscode_folder/Enterprise-grade_RAG/eval/retrieval_samples.yaml)
- [scripts/eval_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_retrieval.py)
- [OPS_SMOKE_TEST.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_SMOKE_TEST.md)
- [Makefile](/home/reggie/vscode_folder/Enterprise-grade_RAG/Makefile)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [\_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/core/_retrieval.py)
- [text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- `eval/results/` 最新结果

---

## 交付物要求

### 1. runbook

补一份 chunk 重建/回滚 runbook。可以：

- 更新 `OPS_SMOKE_TEST.md`
- 或新建单独的 `RETRIEVAL_CHUNK_REBUILD_RUNBOOK.md`

### 2. 必须说清楚的内容

- 是否需要全量重建 embedding
- 是否需要重建 vector index
- metadata / chunks / vectors 的重建顺序
- snapshot / backup 方案
- 回滚入口
- 重建后如何用样本集验证
- baseline 结果应如何记录
- 哪些命令可以真实执行，哪些只能作为 runbook 占位

### 3. Makefile / scripts

只有在命令真实可执行、路径真实存在、风险可控时，才增加新的脚本或 make target。

优先接受：

- 文档优先
- 文档 + 很薄的 orchestration 入口

不要直接做：

- 真正执行大规模 reindex
- 真正开始 chunk 参数扫描
- 真正开始结构化 chunk 规则优化

---

## 验收标准

- 有清晰 runbook
- 有明确验证和回滚步骤
- 有可执行命令或至少清晰命令入口
- 没有引入未经验证的高风险 destructive 自动化
- 明确区分 `2A gate completed` 与 `2B not started`

---

## 可直接发给 GLM 的 Prompt

```text
基于当前仓库状态，开始 Retrieval Phase 2A，但这次只做 `2A / Gate`，不要进入 `2B`。

请先阅读：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- eval/README.md
- eval/retrieval_samples.yaml
- scripts/eval_retrieval.py
- OPS_SMOKE_TEST.md
- Makefile
- backend/app/services/ingestion_service.py
- backend/app/core/_retrieval.py
- backend/app/rag/chunkers/text_chunker.py
- backend/app/rag/chunkers/structured_chunker.py
- eval/results/ 最新结果

当前边界很重要：

- verified baseline 已建立
- 1B-B 仍未正式闭环
- 但这不妨碍先做 `Phase 2A / Gate`
- 这轮目标不是 chunk 优化，而是把“改 chunk 之前需要的重建、验证、回滚路径”补齐

任务：实现 Retrieval Phase 2A，也就是“chunk 改动前的重建与回滚 Gate”。这阶段的目标不是直接改 chunk 逻辑，而是把 runbook、验证路径、回滚路径写清楚，并尽量补成可执行入口。

必须遵守：
1. 如果当前仓库没有足够安全的自动化条件，优先补文档，不要发明高风险 destructive script。
2. 只有当命令真实可执行时，才增加 Makefile target 或脚本。
3. 必须说明 chunk 参数变更对 chunk 文件、embedding、vector index、验证回归的影响。
4. 不直接修改 `text_chunker.py` / `structured_chunker.py` 的行为逻辑。
5. 不直接修改默认 chunk 参数。
6. 不扩 public contract。

请完成：
1. 更新 OPS_SMOKE_TEST.md 或新建一份单独 runbook
2. 写清 chunk 改动前后的重建顺序
3. 写清 snapshot / backup / rollback 步骤
4. 写清如何用 Phase 1 的样本集做重建前后对比验证
5. 如果适合，再增加有限、可验证的 Makefile target 或脚本入口

不要做的事：
- 不要直接改 retrieval 或 chunk 逻辑
- 不要进入 2B
- 不要开始 chunk 参数调优
- 不要假设线上环境细节
- 不要加入未经验证的清库/删索引脚本

完成后请输出：
1. 修改文件列表
2. 你选择“文档优先”还是“文档+脚本”的原因
3. 哪些命令已验证可执行
4. 还不能自动化的部分有哪些
5. 当前是否只完成了 `2A gate`，而不是 `2B`
```
