# Retrieval Phase 3 GLM Prompt

## 这一阶段做什么

在 Phase 1 和 Phase 2 稳定之后，再校准 query router 和 hybrid 权重。

---

## 硬约束

- 不提前跳过样本阶段
- 不用单条 query 证明权重改动是对的
- 不改主契约

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_query_router.py)
- [eval_hybrid_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/eval_hybrid_query_router.py)
- [hybrid_query_router_samples.jsonl](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/fixtures/hybrid_query_router_samples.jsonl)
- [test_hybrid_query_router_samples.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_hybrid_query_router_samples.py)

---

## 交付物要求

- 扩充 router 样本
- 覆盖：
  - 编号
  - 错误码
  - 缩写
  - 文号
  - 条款号
  - mixed query
- 复跑 `scripts/eval_hybrid_query_router.py`
- 在有样本依据时再调阈值和 branch weights

---

## 验收标准

- exact / mixed / semantic 分类更稳
- fine-grained query 不容易掉到 broad semantic
- 权重改动有样本依据

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- backend/app/services/retrieval_query_router.py
- scripts/eval_hybrid_query_router.py
- backend/tests/fixtures/hybrid_query_router_samples.jsonl
- backend/tests/test_hybrid_query_router_samples.py
- backend/tests/test_retrieval_query_router.py

任务：实现 Retrieval Phase 3。目标是扩充 query router 样本，并在样本证据支持下校准 router 阈值和 hybrid 权重。

必须遵守：
1. 不改 API 主契约。
2. 不跳过样本扩充，不能只凭几条 query 直接调权重。
3. 优先复用现有 eval_hybrid_query_router.py，不要另起一套完全重复的工具。

请完成：
1. 扩充 hybrid_query_router_samples.jsonl
2. 覆盖 exact / mixed / semantic / code-like / clause-like query
3. 复跑现有 router 评估脚本
4. 在有明确样本依据时再调整 retrieval_query_router.py 或相关权重配置
5. 更新对应测试

重点关注：
- 缩写、错误码、文号、条款号识别
- fine-grained query 误判为 broad semantic 的情况
- exact query 的 lexical 倾向是否足够
- semantic query 的 vector 倾向是否合理

完成后请输出：
1. 修改文件列表
2. 新增了哪些样本类别
3. 样本评估前后差异
4. 测试命令和结果
5. 还有哪些误判暂时没必要继续修
```
