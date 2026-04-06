# Enterprise-grade_RAG Agent Guide

本仓库使用一套最小可用、单一主线的 coding agent workflow。

## 1. 控制面

`AGENTS.md` 是唯一规则源（Single Source of Truth）。

优先级从高到低：

1. `MAIN_CONTRACT_MATRIX.md`
2. `RETRIEVAL_OPTIMIZATION_PLAN.md`
3. `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
4. `AGENTS.md`
5. `.agent/rules/coding-rules.md`
6. `.agent/context/repo-map.md`
7. `.agent/commands/*.md`
8. `.agent/specs/*.md`

`.claude` 和 `.codex` 只能作为工具适配层，不得再定义业务规则或 workflow 主线。

## 2. 工作原则

- 先读代码、文档和 repo-map，再行动。
- 小改动可直接执行，但仍要先读相关文件。
- 中大改动必须先 `/plan`。
- 复杂改动必须先写 spec。
- 改动必须优先最小必要修改。
- 禁止无关重构、跨模块乱改、顺手清理无关问题。
- 如果发现实现、测试、文档不一致，必须明确指出。

## Lite Mode（快速模式）

Lite Mode 只用于低风险、小范围、单模块改动，用来降低使用成本，但不是绕过约束的通道。

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

## 3. 唯一 workflow 主线

统一主线：

`spec → plan → implement → review`

### 3.1 spec 使用条件

满足任一条件必须先写 spec：

- 新功能
- 跨模块改动
- 影响稳定主契约
- 影响 `retrieval / chat / system-config / ingestion / auth`
- 影响 chunk / rerank / router / hybrid / supplemental
- 需要 backfill / rebuild / rollback

spec 只允许使用：

- `.agent/specs/feature-template.md`
- `.agent/specs/bug-template.md`

### 3.2 `/plan` 强制条件

满足任一条件必须先 `/plan`：

- 中大改动
- 多文件联动
- API / schema / frontend 需要同步
- retrieval 相关改动
- 风险、范围、回滚不清楚

### 3.3 `/review` 强制条件

所有非文档代码改动默认必须 `/review`。
尤其是：

- API / schema 变更
- retrieval / ingestion / chunk / rerank 变更
- 前后端联动变更
- 权限 / scope 变更

### 3.4 Harness v1（仓库内建执行入口）

为避免 workflow 只停留在文本规则层，本仓库提供轻量 harness：

- 规则策略文件：`.agent/harness/policy.yaml`
- 任务声明文件：`.agent/runs/*.yaml`
- 执行入口：`python scripts/agent_harness.py`

默认用法：

1. `make agent-inspect`
2. 对命中的高风险改动补 `.agent/runs/<task>.yaml`
3. `make agent-preflight TASK=.agent/runs/<task>.yaml`
4. 在 plan 边界内实现
5. `make agent-verify TASK=.agent/runs/<task>.yaml`

说明：

- v1 只对 `retrieval`、`ingestion / chunk`、`API / schema` 做强约束。
- Lite 改动默认只给分类和检查建议，不做全面硬阻断。
- harness 不替代 `spec → plan → implement → review`，只负责把已有规则变成可执行检查。
- 高风险任务的 task contract 至少要写清：
  - `task_type`
  - `phase`
  - `allowed_paths`
  - `required_reads`
  - `required_checks`
  - `risk_notes`
  - `expected_artifacts`

## 模型分工（Brain / Executor）

本仓库默认采用“GPT-5.4 当大脑，GLM 当执行器”的协作方式，但不改变主 workflow：

`spec → plan → implement → review`

### GPT-5.4（Brain）

默认负责：

- 先读代码、文档、契约和 repo-map
- 判断是否需要 spec、`/plan`、`/review`
- 定义改动边界、影响文件、风险和验收标准
- 处理高风险决策：
  - 稳定主契约
  - retrieval 优化方向
  - 跨模块改动
  - 回滚、重建、迁移策略
- 在实现完成后做最终 review 和继续 / 暂停判断

### GLM（Executor）

默认负责：

- 在已确认的 spec / plan 边界内执行具体编码
- 落实局部实现、补测试、补文档、补小范围脚本调整
- 按计划做最小必要改动，不自行扩改动范围
- 真实记录改了什么、验证了什么、还有什么风险

### 默认协作顺序

1. GPT-5.4 先完成 spec 或 `/plan`
2. GLM 在明确边界内执行 implement
3. GPT-5.4 最终执行 `/review` 并给出是否继续的结论

### 默认回切原则

如果 GLM 在执行中发现：

- 影响面超出计划
- 触碰 contract / retrieval / schema / frontend 联动边界
- eval、baseline、samples 或验证结果出现异常
- 需要决定取舍、重构方向、回滚策略

则必须停止继续扩写代码，回切给 GPT-5.4 重新判断。

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

## 强制读取规则（Mandatory Reads）

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

## 4. Retrieval 专项约束

retrieval 改动必须遵守固定顺序，禁止跳级修改：

1. baseline
2. supplemental
3. chunk
4. router
5. rerank

即：

- 先评估样本和 baseline
- 再做 supplemental 阈值校准
- 再做 chunk 优化
- 再碰 router / hybrid
- 最后才动 rerank 默认路由

### 4.1 必读依赖

涉及 retrieval 时，默认先读：

- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- `eval/results/` 最新结果
- `RETRIEVAL_OPTIMIZATION_PLAN.md`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`

### 4.2 强约束

- 样本仍是 `draft` / `synthetic` / `placeholder` 时，不允许直接进入 Phase 1B 阈值调优。
- 评估结果几乎全 0 时，先排查：
  - `expected_doc_ids` 是否和真实索引一致
  - 样本是否还是 placeholder
  - 问题属于样本、eval 脚本，还是 retrieval 逻辑
- 不要把启发式字段当成 ground truth。
- `retrieval / chat / SOP` 必须保持同一套 retrieval 主逻辑。
- ingestion / chunk 改动不能破坏 retrieval 现有行为基线。
- rerank 不能先动，除非 baseline、supplemental、chunk、router 已经稳定。

## 失败保护（Failure Guard）

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

## 验证止损与退出条件（Validation Exit Criteria）

当任务进入 `baseline / supplemental / gate stabilization / readiness review` 这类“验证主导”阶段时，必须先定义退出条件，再继续追加验证。

### 1. 目标

- 防止验证工作本身吞掉主线开发节奏
- 防止把环境噪音、HNSW 非确定性或单次波动无限放大为长期 blocker
- 防止为了通过 gate 指标而持续堆 guard / 特判 / 文档包装

### 2. 在继续追加验证前，必须先写清

- 当前层级属于什么：`baseline / supplemental / gate stabilization / readiness review`
- 这轮验证要支持哪一个阶段决策
- 哪些证据会真正改变当前决策
- 最多再补哪些高价值验证：
  - 哪几条行为测试
  - 哪几组样本
  - 最多重复多少次 eval
- 什么算结构性 blocker，什么算可接受的非确定性波动
- 满足什么条件就停止，并输出明确结论

### 3. 结构性 blocker 与可接受波动必须分开

以下更接近结构性 blocker：

- 关键样本稳定回归失败
- 主行为测试无法覆盖核心分支
- baseline 与当前版本差异无法解释
- 单次修复会频繁触碰稳定主契约或跨模块边界

以下更接近可接受波动，不能默认无限追打：

- 近似检索带来的轻微分数抖动
- 在已知范围内、且不改变阶段结论的保守触发波动
- 已被行为测试锁住核心分支后，剩余但可解释的单次排序差异

### 4. 必须停止继续追加验证的情况

满足任一条件，就应停止继续“再跑几次看看”：

- 新增验证已经不能改变阶段结论
- 剩余问题已收敛为已知噪音，而不是新的结构性错误
- 当前轮次已经补齐关键行为测试与最小重复 eval
- 继续追加验证只是在重复证明同一件事，没有新增决策信息

### 5. 明确禁止

- 不允许无限追加 eval 轮次而不预先声明停止条件
- 不允许拿单份最优结果包装成“稳定通过”
- 不允许为了压一个边界指标而持续堆特判，导致主逻辑复杂化
- 不允许把“文档更谨慎”误写成“实现已经完成”

### 6. Retrieval / Gate 推荐 prompt

在需要交给其他 agent 做 gate 审计、稳定性复核或 readiness 判断时，优先附上下面这段：

```md
停止过度验证，先定义退出条件。

- 当前层级：
- 当前要支持的阶段决策：
- 本轮只补哪些高价值证据：
- 哪些现象属于结构性 blocker，哪些属于可接受非确定性：
- 最多再做哪些验证：
  - 哪几条行为测试
  - 哪几组样本
  - 最多几次重复 eval
- 满足什么条件就停止，并输出 pass / not pass / conditionally passed：

如果新增验证已经不能改变阶段结论，就不要继续扩大验证范围；直接收敛文档、证据和下一步建议。
```

## 5. 主契约保护

`MAIN_CONTRACT_MATRIX.md` 是硬约束。

禁止擅自扩或改以下稳定主契约：

- `POST /api/v1/retrieval/search`
- `POST /api/v1/chat/ask`
- `GET /api/v1/system-config`
- `PUT /api/v1/system-config`

如果改动可能碰到主契约，必须同时检查：

- endpoint
- schema
- frontend `api/types.ts`
- frontend `api/client.ts`
- 主契约测试
- 相关文档

禁止只改其中一层。

## 6. 模块隔离要求

默认按模块闭环修改，不要跨模块乱改：

- retrieval 改动优先收敛在 `services/retrieval_*`、`rag/`、eval
- ingestion 改动优先收敛在 `document_service.py`、`ingestion_service.py`、chunk / parser / rebuild
- rerank 改动优先收敛在 `rerankers/client.py`、router、相关测试与 eval
- API / schema 改动优先收敛在 endpoint + schema + frontend API type/client

## 7. 输出格式

每次修改完成后，必须明确说明：

- 改了什么
- 验证了什么
- 风险是什么

如果是文档改动，要明确写：

- 这次是文档改动
- 没有跑代码测试

如果没有完成验证，必须直接说明原因，不能写成“已通过”。
