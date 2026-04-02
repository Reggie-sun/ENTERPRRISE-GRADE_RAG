# Retrieval Phase 2A GLM Prompt

## 这一阶段做什么

在改 chunk 之前，先把“怎么重建、怎么验证、怎么回滚”写清楚。

这是一个 gate 阶段，不是直接改 chunk 逻辑。

---

## 硬约束

- 没有回滚预案，不进入 chunk 改动
- 没有样本验证路径，不进入 chunk 改动
- 如果仓库当前没有足够安全的自动化条件，优先写 runbook，不要硬造高风险 destructive script

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [OPS_SMOKE_TEST.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_SMOKE_TEST.md)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [\_retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/core/_retrieval.py)

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

### 3. Makefile / scripts

只有在命令真实可执行、路径真实存在、风险可控时，才增加新的脚本或 make target。

---

## 验收标准

- 有清晰 runbook
- 有明确验证和回滚步骤
- 没有引入未经验证的高风险 destructive 自动化

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- OPS_SMOKE_TEST.md
- backend/app/services/ingestion_service.py
- backend/app/core/_retrieval.py

任务：实现 Retrieval Phase 2A，也就是“chunk 改动前的重建与回滚 Gate”。这阶段的目标不是直接改 chunk 逻辑，而是把 runbook、验证路径、回滚路径写清楚。

必须遵守：
1. 如果当前仓库没有足够安全的自动化条件，优先补文档，不要发明高风险 destructive script。
2. 只有当命令真实可执行时，才增加 Makefile target 或脚本。
3. 必须说明 chunk 参数变更对 chunk 文件、embedding、vector index、验证回归的影响。

请完成：
1. 更新 OPS_SMOKE_TEST.md 或新建一份单独 runbook
2. 写清 chunk 改动前后的重建顺序
3. 写清 snapshot / backup / rollback 步骤
4. 写清如何用 Phase 1 的样本集做重建前后对比验证
5. 如果适合，再增加有限、可验证的 Makefile target 或脚本入口

不要做的事：
- 不要直接改 retrieval 或 chunk 逻辑
- 不要假设线上环境细节
- 不要加入未经验证的清库/删索引脚本

完成后请输出：
1. 修改文件列表
2. 你选择“文档优先”还是“文档+脚本”的原因
3. 哪些命令已验证可执行
4. 还不能自动化的部分有哪些
```
