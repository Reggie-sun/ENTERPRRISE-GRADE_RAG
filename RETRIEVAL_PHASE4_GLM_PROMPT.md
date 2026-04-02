# Retrieval Phase 4 GLM Prompt

## 这一阶段做什么

最后再看 rerank。

这一阶段的重点不是“直接切默认 provider”，而是先基于 canary 样本复盘质量、延迟和成本。

---

## 硬约束

- 如果 chunk 和候选本身还不稳定，不要提前做 rerank 默认切换
- 不改主契约
- 不凭少量样本就改默认策略

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [rerank_canary_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/rerank_canary_service.py)
- [retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/retrieval.py)
- [test_rerank_canary_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_rerank_canary_endpoints.py)
- [test_ops_endpoints.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_ops_endpoints.py)

---

## 交付物要求

- 复盘 canary 样本
- 如有必要，补一个分析脚本或结果报告模板
- 比较：
  - top1 一致率
  - 排序差异
  - 延迟
  - 成本
- 最终输出建议：
  - 继续 heuristic
  - 继续 observe canary
  - 提升 provider 默认

---

## 验收标准

- 有明确分析依据
- 不靠拍脑袋切默认 rerank
- ops 侧可读性更好

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- backend/app/services/rerank_canary_service.py
- backend/app/api/v1/endpoints/retrieval.py
- backend/tests/test_rerank_canary_endpoints.py
- backend/tests/test_ops_endpoints.py

任务：实现 Retrieval Phase 4。目标是基于 canary 样本复盘 rerank，而不是直接拍脑袋改默认 provider。

必须遵守：
1. 不改 API 主契约。
2. 如果候选质量和 chunk 质量还没收稳，不要直接切默认 rerank。
3. 优先做分析、摘要、证据沉淀，而不是大改路由。

请完成：
1. 复盘现有 rerank canary 样本能力
2. 必要时补一个轻量分析脚本或结果报告格式
3. 让 heuristic vs provider 的差异更容易看懂
4. 给出默认策略建议所需的证据框架

分析至少覆盖：
- top1 consistency
- 排序差异
- 延迟
- 成本
- 建议结论

完成后请输出：
1. 修改文件列表
2. 分析框架或脚本说明
3. 测试命令和结果
4. 当前是否已经有足够证据切默认 rerank，如果没有，缺什么
```
