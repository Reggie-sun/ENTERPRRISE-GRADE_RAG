# Coding Rules

这份规则是本仓库给 coding agent 的本地最小硬约束。

## 1. 总原则

- 先读代码、文档和上下文，再行动。
- 优先最小必要改动，不做无关重构。
- 复杂改动先写 spec，再编码。
- 改完必须给出真实验证依据。
- 如果发现实现、测试、文档不一致，要明确指出具体不一致点。

## 2. 开工前默认读取

至少先看：

1. `MAIN_CONTRACT_MATRIX.md`
2. `RETRIEVAL_OPTIMIZATION_PLAN.md`
3. `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
4. `.agent/context/repo-map.md`

如果任务与 retrieval 或评估相关，再补看：

1. `eval/README.md`
2. `eval/retrieval_samples.yaml`
3. `scripts/eval_retrieval.py`
4. `eval/results/` 最新结果

## 3. 必须先写 spec 的情况

满足以下任一条件时，先 `/plan`，并使用 `.agent/specs/feature-template.md` 或 `.agent/specs/bug-template.md`：

- 新功能
- 跨模块改动
- 可能影响稳定主契约
- 改 retrieval / chat / system-config / ingestion / auth 主链路
- 改 chunk、rerank、router、hybrid、supplemental 判定
- 需要 backfill、重建、迁移、回滚预案

简单单点修复可不写完整 spec，但仍要先读相关代码。

## 4. 契约约束

### 硬约束

- `MAIN_CONTRACT_MATRIX.md` 是硬约束。
- 不要擅自扩稳定主契约。
- 不要改稳定字段语义。

### 高风险稳定接口

- `POST /api/v1/retrieval/search`
- `POST /api/v1/chat/ask`
- `GET /api/v1/system-config`
- `PUT /api/v1/system-config`

### 如果碰到契约

必须同时检查：

- 对应 endpoint
- 对应 schema
- `backend/tests/test_main_contract_endpoints.py`
- `backend/tests/test_main_contract_errors.py`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- 相关文档

## 5. Retrieval / RAG 规则

### 优化顺序

1. 先评估样本与 baseline
2. 再做 supplemental 阈值校准
3. 再做 chunk 优化
4. 再碰 router / hybrid
5. 最后才动 rerank 默认路由

### 评估规则

- 样本仍是 `draft`、`synthetic`、`placeholder` 时，不进入 Phase 1B 阈值调优。
- 评估结果几乎全 0 时，先检查：
  - `expected_doc_ids` 是否与真实索引一致
  - 样本是否仍是 synthetic placeholder
  - 问题属于样本、评估脚本，还是检索逻辑
- 不要把启发式字段当成 ground truth。
- 不要把 placeholder baseline 说成真实运行时快照。

### 一致性规则

- `retrieval / chat / SOP` 默认保持同一套 retrieval 主逻辑。
- 不要为单个 endpoint 临时分叉 supplemental 或 rerank 规则。

## 6. 后端改动规则

- HTTP 层改动，优先落在：
  - `backend/app/api/v1/endpoints/`
  - `backend/app/schemas/`
  - `backend/app/services/`
- 不要把业务逻辑直接堆回 endpoint。
- 配置变更优先从 `system_config_service.py` 或 `core/config.py` 找真源，不要新增散落常量。
- 受保护接口默认要保留认证和 scope 约束。
- 错误返回要保持当前错误包约定，不要静默改形状。

## 7. 前端改动规则

- 接口消费统一经过 `frontend/src/api/`，不要到页面里临时拼 fetch。
- 后端字段变化通常要同步：
  - `frontend/src/api/types.ts`
  - `frontend/src/api/client.ts`
  - 对应 page / panel / component
- 路由和权限边界以 `frontend/src/App.tsx`、`frontend/src/auth/` 为准，不要绕过守卫逻辑。
- 不要为了一个页面需求复制一套新的 API 类型或 client。

## 8. 范围控制

- 不顺手重构无关模块。
- 不顺手清理与本任务无关的 warning。
- 不顺手搬目录、改命名、统一风格。
- 如果现有模式能复用，优先复用，不要引入新框架式抽象。

## 9. 验证要求

### 至少做针对性验证

- 后端改动：
  - 优先跑相关 `pytest` 文件
- 前端改动：
  - 至少跑 `cd frontend && npm run lint`
  - 需要时补 `cd frontend && npm run build`
- 文档 / ingestion 流程：
  - 需要时跑 `make test-smoke-v02`
- retrieval 行为：
  - 需要时跑 `make eval-retrieval`

### 如果没法验证

- 直接说明原因
- 不要写成“已通过”

### 纯文档改动

- 要明确说明没有跑代码测试

## 10. 交付格式

结论必须优先写：

1. 改了什么
2. 验证了什么
3. 还有什么风险或缺口

如果是 review：

- 先列问题，再给总结
- 重点找 bug、风险、行为回归、缺失测试
- 如果没有发现明确问题，要直接写“未发现明确问题”，再补残余风险和测试缺口
