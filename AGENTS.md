This file defines repository-specific instructions for Codex in Enterprise-grade_RAG.

本仓库的硬约束：
- `MAIN_CONTRACT_MATRIX.md` 是硬约束。
- 不要擅自扩稳定主契约，不要改稳定字段语义，尤其是：
  - `POST /api/v1/retrieval/search`
  - `POST /api/v1/chat/ask`
  - `GET /api/v1/system-config`
  - `PUT /api/v1/system-config`
- 如果改动可能碰到 contract，先核对 `MAIN_CONTRACT_MATRIX.md`，再行动。
- 如果发现实现、测试、文档三者不一致，要明确指出具体不一致点。

在本仓库工作时，默认先读：
- `MAIN_CONTRACT_MATRIX.md`
- `RETRIEVAL_OPTIMIZATION_PLAN.md`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`

关于 retrieval 优化，默认遵守：
- 先评估样本与 baseline
- 再做 supplemental 阈值校准
- 再做 chunk 优化
- 再碰 router / hybrid
- 最后才动 rerank 默认路由

关于 retrieval 评估：
- 在样本仍是 `draft`、`synthetic`、`placeholder` 时，不要直接进入 Phase 1B 阈值调优。
- 如果评估结果几乎全 0，先检查：
  - `expected_doc_ids` 是否和真实索引一致
  - 样本是否还是 synthetic placeholder
  - 是样本集问题还是检索逻辑问题
- 不要把启发式字段当成 ground truth。
- 不要把 placeholder baseline 说成真实运行时快照。

关于样本与评估脚本：
- 与 retrieval 优化相关时，优先查看：
  - `eval/README.md`
  - `eval/retrieval_samples.yaml`
  - `scripts/eval_retrieval.py`
  - `eval/results/` 下最新结果
- 如果要推进 Phase 1B，先确认至少已有一小批 verified samples。
- 如果当前库里没有足够可验证的真实文档，不要硬编样本；要明确说明缺口。

工作方式：
- 优先最小必要改动，不要顺手重构无关模块。
- 改完后做针对性验证，并在结论里说明：
  - 改了什么
  - 验证了什么
  - 还有什么风险
