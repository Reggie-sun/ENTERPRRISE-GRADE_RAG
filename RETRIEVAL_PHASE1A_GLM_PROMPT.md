# Retrieval Phase 1A GLM Prompt

## 这一阶段做什么

先把检索评估基础设施搭起来，不直接改 retrieval 行为。

目标是补齐这些东西：

- `eval/retrieval_samples.yaml`
- `eval/README.md`
- `eval/baseline_config_snapshot.yaml`
- `scripts/eval_retrieval.py`
- `Makefile` 里的 `make eval-retrieval`

---

## 硬约束

- 必须遵守 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)
- 不新增 `retrieval/search`、`chat/ask`、`system-config` 的稳定 public 字段
- 不改现有 API 响应字段语义
- 不直接调整 retrieval 逻辑
- 受保护接口必须走登录态

---

## 开工前必须先读

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)
- [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md)
- [retrieval.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/retrieval.py)
- [auth.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/api/v1/endpoints/auth.py)

---

## 交付物要求

### 1. 样本文件

- 建立 `eval/` 目录
- 创建 `eval/retrieval_samples.yaml`
- 不要伪造“看起来真实但其实没有依据”的 40 条业务样本
- 可以先提供：
  - 明确的 schema
  - 8 到 12 条示例样本
  - 用 `status: draft` 或 `source: synthetic` 明确标记为占位样本

### 2. 样本说明文档

- 创建 `eval/README.md`
- 里面必须写清：
  - 样本字段含义
  - 判分规则
  - `top1_accuracy` / `top1_partial_hit` / `topk_recall`
  - `supplemental` 的判对规则
  - 多文档期望怎么记分

### 3. baseline 配置快照

- 创建 `eval/baseline_config_snapshot.yaml`
- 至少包含：
  - supplemental 4 个阈值
  - chunk 参数
  - dynamic weighting 开关
  - rerank compare 开关
  - 当前 commit hash 占位字段
  - 当前数据集/索引版本占位字段

### 4. retrieval 评估脚本

- 新建 `scripts/eval_retrieval.py`
- 支持：
  - 读取样本 YAML
  - 登录获取 token
  - 调用受保护的 retrieval endpoint
  - 输出 JSON 报告
  - 控制 API base url
  - 指定样本文件路径
- 如果本地 API 未启动，要给出清晰错误信息，不要静默失败

### 5. Makefile

- 增加 `make eval-retrieval`

---

## 验收标准

- 能运行 `make eval-retrieval`
- 样本 schema 清晰
- 判分规则清晰
- 脚本走登录态
- 不改主契约

---

## 可直接发给 GLM 的 Prompt

```text
你现在在仓库 /home/reggie/vscode_folder/Enterprise-grade_RAG 工作。

请先阅读以下文件，再开始修改：
- RETRIEVAL_OPTIMIZATION_PLAN.md
- RETRIEVAL_OPTIMIZATION_BACKLOG.md
- MAIN_CONTRACT_MATRIX.md
- backend/app/api/v1/endpoints/retrieval.py
- backend/app/api/v1/endpoints/auth.py

任务：实现 Retrieval Phase 1A，只做“检索评估基础设施”，不要改 retrieval 行为本身。

必须遵守：
1. 不新增 retrieval/search、chat/ask、system-config 的稳定 public 字段。
2. 不改变现有稳定字段语义。
3. 受保护接口必须通过登录获取 Bearer token 后调用。
4. 不要伪造大量看似真实的业务样本；如果缺少真实数据，请提供 schema + 少量 synthetic draft samples，并明确标记。

请完成以下交付：
1. 创建 eval/retrieval_samples.yaml
2. 创建 eval/README.md，明确样本字段和评分规则
3. 创建 eval/baseline_config_snapshot.yaml
4. 创建 scripts/eval_retrieval.py
5. 在 Makefile 中增加 make eval-retrieval

对 eval_retrieval.py 的要求：
- 支持 --api-base
- 支持 --samples
- 支持登录并获取 token
- 调用受保护的 retrieval endpoint
- 输出 JSON 结果到 eval/results/
- API 未启动或登录失败时给出清晰报错

评分规则必须显式覆盖：
- top1_accuracy
- top1_partial_hit
- topk_recall
- expected_doc_coverage
- supplemental_precision / supplemental_recall
- conservative_trigger_count

完成后请：
1. 列出修改的文件
2. 说明你做了哪些设计取舍
3. 给出运行的命令和结果
4. 说明还有哪些地方只是 scaffold / placeholder
```
