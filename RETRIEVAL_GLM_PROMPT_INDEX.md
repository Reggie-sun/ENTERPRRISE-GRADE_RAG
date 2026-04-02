# Retrieval GLM Prompt Index

这组文档是给 GLM 用的“分阶段执行包”。

默认前提：

- 你本机的 `~/.claude/Claude.md` 已经提供仓库定位、通用协作约束和基础工作习惯
- 因此这里的阶段 prompt 可以尽量只保留“这次任务特有的信息”
- 不需要每次都重复写“你现在在仓库 … 工作”或长篇“请先阅读以下文件”，除非你要把 prompt 发给一个不共享这些全局上下文的模型环境

使用方式：

1. 不要一次把所有阶段都丢给 GLM。
2. 按顺序一份一份执行。
3. 每个阶段完成后，先看改动和测试结果，再决定是否进入下一阶段。
4. 任何阶段都必须遵守 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)。

---

## 推荐顺序

1. [RETRIEVAL_PHASE1A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_GLM_PROMPT.md)
2. [RETRIEVAL_PHASE1A_PATCH_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_PATCH_GLM_PROMPT.md)
3. [RETRIEVAL_PHASE1B_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1B_GLM_PROMPT.md)
4. [RETRIEVAL_PHASE2A_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE2A_GLM_PROMPT.md)
5. [RETRIEVAL_PHASE2B_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE2B_GLM_PROMPT.md)
6. [RETRIEVAL_PHASE3_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE3_GLM_PROMPT.md)
7. [RETRIEVAL_PHASE4_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE4_GLM_PROMPT.md)

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

- `1B-A`：先补实验能力、diagnostics 一致性、关键回归和实验记录。
- `1B-B`：在补齐 `supplemental_expected=true` verified 样本，并具备部门隔离视角的评估能力后，再做 supplemental 阈值定版。

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
- 如果第一轮 Phase 1A 交付只完成了 scaffold，但默认运行方式、账号、部门上下文或 `chunk_type` 评分仍有缺口，就先给它 [RETRIEVAL_PHASE1A_PATCH_GLM_PROMPT.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_PHASE1A_PATCH_GLM_PROMPT.md) 再进入 Phase 1B。
- 如果你要进入 Phase 1B，先确认当前是在做 `1B-A` 还是 `1B-B`：
  - 如果 verified 样本里 `supplemental_expected=true` 仍为 0，就先做 `1B-A`
  - 如果 verified 样本已经补齐，但评估仍跑在 `sys_admin` 全量视角、没有部门隔离，就先补 `1B-B` 的前置条件
  - 只有 cross-dept verified samples 和部门隔离评估能力都具备后，才进入真正的 `1B-B`
- 如果你要 GLM 先做文档和脚手架而不是动检索逻辑，就先给它 Phase 1A 或 Phase 2A。

---

## Prompt 风格建议

如果你的全局 Claude 配置已经稳定提供仓库上下文，推荐使用“瘦 prompt”：

- 保留：当前 blocker、这次任务、不要做的事、最后要输出什么
- 省略：重复的仓库路径声明、重复的通用读文件清单

只有在以下情况，才建议写回“完整 prompt”：

- prompt 会被转发到不共享你本机全局上下文的模型环境
- 你希望强制模型重新聚焦某几个关键文件
- 你发现模型有明显跳读、漏读或跑偏
