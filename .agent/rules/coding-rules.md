# Coding Rules

这份规则是本仓库给 coding agent 的本地最小硬约束。

## 1. 总原则

- 先读代码、文档和上下文，再行动。
- 优先最小必要改动，不做无关重构。
- 复杂改动先写 spec，再编码。
- 改完必须给出真实验证依据。
- 如果发现实现、测试、文档不一致，要明确指出具体不一致点。

## 2. Lite Mode（快速模式）

Lite Mode 只用于低风险、小范围、单模块改动，不是绕过约束的通道。

### 允许进入 Lite Mode 的条件

只有同时满足以下条件，才允许跳过 spec，直接进入实现：

- 改动范围小，通常为 1 到 3 个相关文件
- 目标明确，是局部修复、文案修正、局部行为微调或纯前端展示修正
- 不涉及稳定主契约
- 不新增 endpoint、不新增公共字段、不改变字段语义
- 不影响 `retrieval / ingestion / chunk / router / rerank / supplemental`
- 不需要 backfill、rebuild、迁移、回滚预案
- 不需要前后端跨层联动改造
- 不涉及权限、scope、system-config 真源、worker 行为

### 禁止使用 Lite Mode 的情况

满足任一情况，必须退出 Lite Mode，回到标准主线：

- 需要改 schema、API、frontend API 类型或 client
- 需要改 retrieval、ingestion、chunk、rerank、router、eval
- 需要改系统配置真源、认证、权限、部门隔离
- 需要改动超过一个模块边界
- 对风险、影响面、回滚方式不确定
- 发现实现、测试、文档存在不一致

### Lite Mode 下仍然强制执行的动作

即使进入 Lite Mode，也仍然必须：

- 先读相关代码、相关文档、相关测试
- 明确本次改动的边界
- 做最小必要改动
- 运行最小但真实的验证
- 完成 `/review`
- 在结论中说明：
  - 改了什么
  - 验证了什么
  - 风险是什么

### Lite Mode 退出规则

如果实现过程中发现实际影响超出预期，必须立刻停止继续编码，切回标准主线：

`spec → plan → implement → review`

## 3. 开工前默认读取

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

## 4. 强制读取规则（Mandatory Reads）

按模块修改前，必须先读对应文件。**未读取前禁止修改。**

### 1. Retrieval 模块

涉及以下任一内容时，先读：

- `retrieval`
- `supplemental`
- `router / hybrid`
- `rerank`
- `eval`
- `retrieval diagnostics`

必须先读：

- `MAIN_CONTRACT_MATRIX.md`
- `RETRIEVAL_OPTIMIZATION_PLAN.md`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- `backend/app/services/retrieval_service.py`

按需补读：

- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/services/retrieval_scope_policy.py`
- `backend/app/rag/rerankers/client.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_retrieval_query_router.py`
- `backend/tests/test_retrieval_diagnostics.py`

**未完成上述读取前，禁止修改 retrieval 逻辑。**

### 2. Ingestion / Chunk 模块

涉及以下任一内容时，先读：

- 文档入库
- parser
- chunk
- rebuild
- embeddings 入库链路

必须先读：

- `MAIN_CONTRACT_MATRIX.md`
- `RETRIEVAL_OPTIMIZATION_PLAN.md`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
- `backend/app/services/document_service.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/rag/chunkers/text_chunker.py`
- `backend/app/rag/chunkers/structured_chunker.py`
- `scripts/rebuild_documents.py`

按需补读：

- `backend/app/rag/parsers/document_parser.py`
- `OPS_CHUNK_REBUILD_RUNBOOK.md`
- `eval/README.md`
- `scripts/eval_retrieval.py`

**未完成上述读取前，禁止修改 ingestion / chunk。**

### 3. API / Contract 模块

涉及以下任一内容时，先读：

- endpoint
- request / response 字段
- 错误包
- system-config
- chat / retrieval 主接口

必须先读：

- `MAIN_CONTRACT_MATRIX.md`
- 对应 endpoint 文件
- 对应 schema 文件
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `backend/tests/test_main_contract_endpoints.py`
- `backend/tests/test_main_contract_errors.py`

按需补读：

- 对应 service 文件
- 对应页面 / panel 文件
- 相关文档或 runbook

**未完成上述读取前，禁止修改 API / contract。**

### 4. Schema 模块

涉及 schema、字段、模型、错误包时，必须先读：

- 对应 schema 文件
- 对应 endpoint 文件
- 对应 service 文件
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`

如果该 schema 属于稳定主契约面，再额外必须读：

- `MAIN_CONTRACT_MATRIX.md`
- `backend/tests/test_main_contract_endpoints.py`
- `backend/tests/test_main_contract_errors.py`

**未完成上述读取前，禁止修改 schema。**

### 5. 不确定归属时

如果无法判断改动属于哪个模块：

- 先停止修改
- 先补读 `.agent/context/repo-map.md`
- 再按“影响最大模块”执行 Mandatory Reads
- 如果仍不清楚，必须先 `/plan`

## 自动触发规则（Auto Enforcement）

命中以下任一改动类型时，必须自动进入对应 workflow，不得靠主观判断跳过。

### 1. Retrieval 改动

如果修改了以下任一内容，即视为命中 retrieval 改动：

- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/services/retrieval_scope_policy.py`
- `backend/app/rag/rerankers/client.py`
- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- retrieval / router / rerank / diagnostics 相关测试

则必须：

- 先完成 Retrieval 对应的 Mandatory Reads
- 默认进入 `/plan`
- 按复杂改动判断是否需要 feature spec 或 bug spec
- 完成 `/review`
- 运行 eval，或明确说明当前为什么无法运行 eval

并且禁止：

- 未读 `eval/README.md`、`eval/retrieval_samples.yaml`、`scripts/eval_retrieval.py` 就修改 retrieval
- 跳过 baseline / samples / backlog
- 先动 rerank
- 用 rerank 掩盖 retrieval / chunk / router 问题

### 2. Ingestion / Chunk 改动

如果修改了以下任一内容，即视为命中 ingestion / chunk 改动：

- `backend/app/services/document_service.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/rag/chunkers/text_chunker.py`
- `backend/app/rag/chunkers/structured_chunker.py`
- `backend/app/rag/parsers/document_parser.py`
- `scripts/rebuild_documents.py`

则必须：

- 先完成 Ingestion / Chunk 对应的 Mandatory Reads
- 默认进入 `/plan`
- 如果影响切块策略、重建流程、入库边界，必须先写 spec
- 完成 `/review`
- 把 retrieval 作为回归面检查

并且禁止：

- 只改 chunk 不看 retrieval 回归
- 在 baseline 不清楚时推进 chunk 调优
- 不说明 rebuild / rollback / 验证方式就修改入库链路

### 3. API / Schema 改动

如果修改了以下任一内容，即视为命中 API / schema 改动：

- `backend/app/api/v1/endpoints/*`
- `backend/app/schemas/*`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- 主契约相关测试

则必须：

- 先完成 API / Contract 或 Schema 对应的 Mandatory Reads
- 若涉及稳定主契约，必须 `/plan`
- 若涉及多层联动或行为变更，必须先写 spec
- 完成 `/review`
- 同步检查 frontend API 类型和 client

并且禁止：

- 只改 endpoint 不改 schema
- 只改 schema 不查 frontend
- 碰稳定主契约却不核对 `MAIN_CONTRACT_MATRIX.md`

### 4. Lite 场景

如果改动同时满足以下条件，则可进入 Lite Mode：

- 文件少，通常 1 到 3 个
- 不涉及 retrieval / ingestion / chunk / router / rerank / supplemental
- 不涉及 schema / API / auth / system-config / worker
- 不跨模块边界

即使进入 Lite Mode，也仍然必须：

- 先读相关代码和测试
- 做最小必要改动
- 完成 `/review`
- 做最小真实验证
- 在结论中说明改了什么、验证了什么、风险是什么

并且禁止：

- 把 retrieval / schema / ingestion 改动伪装成 lite 改动
- Lite Mode 下跳过 `/review`
- Lite Mode 下跳过验证

## 执行提醒（Execution Hints）

开始修改前，先做这 5 个判断：

1. 这次改动是否命中 retrieval / ingestion / API / schema？
2. 如果命中，是否已经完成对应 Mandatory Reads？
3. 这次改动是否已经达到必须 `/plan` 的条件？
4. 这次改动是否已经达到必须写 spec 的条件？
5. 这次改动完成后，是否必须 `/review`、是否必须跑 eval / smoke / frontend 校验？

默认规则：

- 不确定是否需要 `/plan`：先 `/plan`
- 不确定是否需要 spec：先按复杂改动处理
- 不确定是否需要读取文件：先读再改
- 不确定是否能跳过 `/review`：不能跳过

## 防绕过规则（Anti-bypass Rules）

以下行为视为绕过 workflow，默认禁止：

### 1. Retrieval 防绕过

- 不允许直接修改 retrieval 逻辑而不读取 eval / samples / backlog
- 不允许直接修改 retrieval 逻辑而不做 eval，或不说明 eval 阻塞原因
- 不允许在 baseline 不可复现时继续做 retrieval 优化
- 不允许使用 placeholder / synthetic 样本直接做调优

### 2. Schema / API 防绕过

- 不允许 schema 改动不检查 frontend
- 不允许 endpoint 改动不检查 schema
- 不允许稳定主契约改动不核对 `MAIN_CONTRACT_MATRIX.md`
- 不允许只改一层而假设其他层会自动兼容

### 3. Review 防绕过

- 不允许任何非文档代码改动跳过 `/review`
- 不允许以 Lite Mode 为理由跳过 `/review`
- 不允许以“只是小修”为理由跳过边界 / 契约 / 回归检查

### 4. Rerank 防绕过

- 不允许先改 rerank 再回头解释 retrieval / chunk / router 问题
- 不允许用 rerank 掩盖 baseline、supplemental、chunk、router 未稳定的问题
- 不允许在 retrieval 已退化时继续通过 rerank 做表面修饰

### 5. 范围防绕过

- 不允许借一次局部任务顺手做无关重构
- 不允许跨模块扩散改动却不升级为 `/plan` 或 spec
- 不允许在影响面不清楚时继续直接编码

## GLM 回切条件（Escalation Back to Brain）

默认角色分工是：

- GPT-5.4：负责读上下文、定边界、做高风险判断、做最终 review
- GLM：负责在已确认边界内执行具体编码

GLM 不负责独立定义高风险方向。满足以下任一条件时，必须停止继续编码并回切 GPT-5.4：

- 发现需要改稳定主契约、API、schema 或前端联动
- 发现 retrieval 优化方向需要重新判断：
  - baseline
  - supplemental
  - chunk
  - router / hybrid
  - rerank
- 发现 samples、baseline、eval 结果不可信
- 发现影响文件超出 spec / plan 既定范围
- 发现需要跨模块联动才能收敛问题
- 发现现有 plan 不足以支撑实现决策
- 发现验证结果异常、行为退化或回归风险无法解释
- 发现需要决定回滚、重建、迁移、数据修复策略

GLM 默认禁止：

- 自行扩大改动范围
- 自行决定 contract 语义变更
- 自行推进 retrieval 策略改写
- 用临时 patch 掩盖 schema、retrieval、chunk 或 router 的根因问题

## 5. 必须先写 spec 的情况

满足以下任一条件时，先 `/plan`，并使用 `.agent/specs/feature-template.md` 或 `.agent/specs/bug-template.md`：

- 新功能
- 跨模块改动
- 可能影响稳定主契约
- 改 retrieval / chat / system-config / ingestion / auth 主链路
- 改 chunk、rerank、router、hybrid、supplemental 判定
- 需要 backfill、重建、迁移、回滚预案

简单单点修复可不写完整 spec，但仍要先读相关代码。

## 6. 契约约束

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

## 7. Retrieval / RAG 规则

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
- ingestion / chunk 修改不能破坏 retrieval 行为基线。
- rerank 只能放在 baseline、supplemental、chunk、router 之后。

## 8. 失败保护（Failure Guard）

以下情况视为异常状态。进入异常状态后，默认停止继续开发，先恢复证据链，再决定是否继续实现。

### 1. 异常情况定义

#### eval 异常

满足任一情况即视为 eval 异常：

- `scripts/eval_retrieval.py` 运行失败
- eval 输出结构异常、结果不可解析
- 指标大面积归零，但无法证明是预期结果
- 当前结果与样本、索引、配置明显不匹配

#### retrieval 退化

满足任一情况即视为 retrieval 退化：

- baseline 相比，核心命中指标明显下降
- top1 / topk 命中出现持续回退
- 原本稳定 query 在同样配置下出现明显劣化
- chat / SOP 引用质量因 retrieval 改动明显变差

#### placeholder 样本

满足任一情况即视为样本不可用：

- 样本仍是 `draft`
- 样本仍是 `synthetic`
- 样本仍是 `placeholder`
- `expected_doc_ids` 无法和真实索引对应

#### baseline 不可复现

满足任一情况即视为 baseline 不可复现：

- baseline 配置来源不清楚
- baseline 结果无法复跑
- baseline 对应样本集不明确
- baseline 与当前索引 / 配置 / 数据版本不一致

### 2. 必须停止开发的条件

满足以下任一条件，必须停止继续改代码：

- eval 异常，且未确认是脚本问题还是逻辑问题
- retrieval 退化，且原因尚未定位
- 使用 placeholder / synthetic 样本进行阈值或排序调优
- baseline 不可复现却继续拿来做对比
- ingestion / chunk 改动后 retrieval 明显退化
- 试图通过先调 rerank 去掩盖 baseline、supplemental、chunk、router 问题

### 3. 停止后禁止做的事

进入 Failure Guard 后，禁止：

- 继续调阈值“碰碰运气”
- 继续扩改动范围
- 先改 rerank 掩盖问题
- 在样本和 baseline 不可信的前提下继续优化 retrieval

### 4. 恢复流程

进入异常状态后，按以下顺序恢复：

1. 停止新增改动
2. 记录当前异常：
   - 现象
   - 涉及样本
   - 涉及配置
   - 涉及索引 / 数据版本
3. 先判断异常来源属于哪一类：
   - 样本问题
   - eval 脚本问题
   - baseline 问题
   - retrieval 逻辑问题
   - ingestion / chunk 连带问题
4. 修复证据链：
   - 样本不可信，先修样本
   - baseline 不可复现，先重建 baseline
   - eval 不可用，先修 eval
5. 在同一批样本、同一配置、同一索引条件下重新跑：
   - baseline
   - 当前版本
6. 只有在证据链恢复后，才允许继续开发

### 5. 恢复后的继续条件

只有同时满足以下条件，才允许退出 Failure Guard：

- eval 可稳定运行
- baseline 可复现
- 样本不是 placeholder / synthetic / draft 主体
- 当前版本相对 baseline 的变化可解释
- retrieval 没有出现未解释的退化

未满足以上条件，必须继续停机排查，不得进入下一阶段优化。

## 9. 后端改动规则

- HTTP 层改动，优先落在：
  - `backend/app/api/v1/endpoints/`
  - `backend/app/schemas/`
  - `backend/app/services/`
- 不要把业务逻辑直接堆回 endpoint。
- 配置变更优先从 `system_config_service.py` 或 `core/config.py` 找真源，不要新增散落常量。
- 受保护接口默认要保留认证和 scope 约束。
- 错误返回要保持当前错误包约定，不要静默改形状。

## 10. 前端改动规则

- 接口消费统一经过 `frontend/src/api/`，不要到页面里临时拼 fetch。
- 后端字段变化通常要同步：
  - `frontend/src/api/types.ts`
  - `frontend/src/api/client.ts`
  - 对应 page / panel / component
- 路由和权限边界以 `frontend/src/App.tsx`、`frontend/src/auth/` 为准，不要绕过守卫逻辑。
- 不要为了一个页面需求复制一套新的 API 类型或 client。

## 11. 范围控制

- 不顺手重构无关模块。
- 不顺手清理与本任务无关的 warning。
- 不顺手搬目录、改命名、统一风格。
- 如果现有模式能复用，优先复用，不要引入新框架式抽象。
- 不要跨模块乱改。优先在当前问题所属模块内闭环：
  - retrieval 改动先收敛在 `services/retrieval_*`、`rag/`、eval 相关文件
  - ingestion 改动先收敛在 `document_service.py`、`ingestion_service.py`、chunk / parser / rebuild 脚本
  - rerank 改动先收敛在 `rerankers/client.py`、query router、相关测试与 eval
  - API / schema 变更先收敛在 endpoint + schema + frontend API type/client

## 12. 验证要求

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

## 13. 交付格式

结论必须优先写：

1. 改了什么
2. 验证了什么
3. 还有什么风险或缺口

如果是 review：

- 先列问题，再给总结
- 重点找 bug、风险、行为回归、缺失测试
- 如果没有发现明确问题，要直接写“未发现明确问题”，再补残余风险和测试缺口
