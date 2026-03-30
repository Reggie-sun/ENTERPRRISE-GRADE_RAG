# Retrieval Optimization Backlog

> 更新时间：`2026-03-30`
>
> 目标：把当前仓库里“已经落地但尚未完全收口”的检索能力，整理成一组可直接执行的 issue backlog。

## 1. 当前判断

当前阶段适合做的是：

- `hybrid retrieval` 的验证、治理、配置收口
- `model rerank` 的生产化验证与默认路由收口
- 检索解释性、可观测性、回归测试补齐

当前阶段不建议做的是：

- 切换 `Qdrant` 主链路
- 引入 `pgvector / Elasticsearch / OpenSearch`
- 重做 chunk 规则
- 提前做复杂 `query rewrite` 编排
- 提前做多索引、多阶段检索重构

一句话说：现在适合做“检索质量增强”，不适合做“大检索重构”。

---

## 2. 当前代码锚点

这轮 backlog 主要围绕下面这些文件收口：

- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/rag/rerankers/client.py`
- `backend/app/services/system_config_service.py`
- `backend/app/schemas/retrieval.py`
- `backend/app/schemas/request_snapshot.py`
- `backend/app/services/request_snapshot_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_query_profile_service.py`
- `backend/tests/test_reranker_client.py`
- `backend/tests/test_sop_generation_service.py`

当前已经具备的能力：

- 在线主检索已经是 `vector + lexical + weighted RRF fusion`
- 已支持“部门优先 + 全局补充”的两路召回与融合
- 已具备 `dynamic weighting` 的规则分类与分支权重
- 已具备 `model rerank provider + heuristic fallback`
- 已具备 `compare_rerank + canary sample`
- chat 与 SOP 已复用统一检索入口和统一 rerank 降级逻辑

因此，后续工作重点不是“再补第一版检索能力”，而是把现有能力从“能跑”推进到“能解释、能回滚、能灰度、能验证”。

---

## 3. 建议执行顺序

建议按下面顺序推进：

1. `Rerank` 默认路由与回滚策略收口
2. `Dynamic Weighting` 配置收口到系统配置真源
3. 真实业务 `query` 样本集与首轮校准
4. 检索解释性字段统一到 `retrieval/chat/snapshot/SOP`
5. 双链路一致性与回归矩阵补齐

---

## 4. Issue Backlog

### Issue 1

**标题**

`feat(retrieval): 收口 Model Rerank 默认路由与回滚策略`

**目标**

把当前 `heuristic / provider` 双路径收口成正式在线能力，明确默认策略、失败回退、健康冷却、compare 口径和切换条件。

**背景**

当前代码已经具备：

- `RerankerClient.rerank()`
- `RerankerClient.rerank_provider_candidate()`
- `QueryProfileService.rerank_with_fallback()`
- `RetrievalService.compare_rerank()`
- `RerankCanaryService.record_compare_sample()`

缺的不是能力入口，而是“生产默认怎么跑”的最后一层收口。

**主要工作**

- 明确 `default_strategy = heuristic | provider` 的正式运行语义
- 明确 provider 健康检查失败、请求失败、超时、`429` 时的统一回退路径
- 明确冷却锁窗口内的行为和诊断字段
- 明确 `compare_rerank` 的推荐结论什么时候允许切默认
- 确保 chat 与 SOP 看到的 rerank 行为和日志语义一致

**涉及文件**

- `backend/app/rag/rerankers/client.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/services/rerank_canary_service.py`

**验收标准**

- `default_strategy=provider` 且 provider 健康时，主链路默认走 provider
- provider 失败时，系统自动回退到 `heuristic`
- 回退后运行态能看到锁定来源、剩余冷却时间、当前生效策略
- `compare_rerank` 能稳定返回 `configured / heuristic / provider_candidate / recommendation`
- chat 与 SOP 的 `rerank_strategy / rerank_provider / rerank_model` 解释语义一致

**明确不做**

- 不改异步入库链路
- 不重跑 embedding
- 不单独为 rerank 另造一套 query profile

---

### Issue 2

**标题**

`feat(system-config): 把 Dynamic Weighting 从 Settings 收口到系统配置真源`

**目标**

让 `dynamic weighting` 从 `.env` 级参数变成可配置、可灰度、可回退的系统配置能力。

**背景**

当前 `dynamic weighting` 已经在代码里存在，但主要依赖静态配置：

- `retrieval_dynamic_weighting_enabled`
- `retrieval_hybrid_fixed_*`
- `retrieval_hybrid_exact_*`
- `retrieval_hybrid_semantic_*`
- `retrieval_hybrid_mixed_*`
- `retrieval_query_classifier_*`

这意味着后续真实样本校准会被“改配置要重启”拖慢，也不方便灰度。

**主要工作**

- 为 `dynamic weighting` 增加系统配置模型
- 把开关、阈值、权重统一接入系统配置真源
- 保留默认关闭的基线策略
- 明确 fixed fallback 的回退口径
- 补系统配置读写校验

**建议配置项**

- `enabled`
- `fixed.vector_weight`
- `fixed.lexical_weight`
- `exact.vector_weight`
- `exact.lexical_weight`
- `semantic.vector_weight`
- `semantic.lexical_weight`
- `mixed.vector_weight`
- `mixed.lexical_weight`
- `exact_signal_threshold`
- `semantic_signal_threshold`

**涉及文件**

- `backend/app/core/config.py`
- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/system_config_service.py`
- `backend/app/schemas/system_config.py`
- `backend/tests/test_system_config_service.py`
- `backend/tests/test_retrieval_chat.py`

**验收标准**

- 管理端可读取与更新 dynamic weighting 配置
- 非法权重或阈值会被校验拦截
- dynamic weighting 默认保持关闭
- 关闭时回退 fixed fallback，且不破坏当前排序基线
- 开启时 `exact / semantic / mixed` 权重能被实际命中并可观测

**明确不做**

- 不在前端公开一堆实验性检索策略按钮
- 不把规则分类直接替换成模型分类

---

### Issue 3

**标题**

`chore(retrieval): 建真实业务 Query 样本集并完成首轮校准`

**目标**

把当前规则和权重从“凭经验默认值”推进到“基于真实业务 query 的可解释校准”。

**背景**

当前仓库已经有一批功能级测试样例，但还缺真实业务 query 集合作为决策依据。没有样本，就无法合理决定：

- `dynamic weighting` 值不值得灰度开启
- `exact / semantic / mixed` 阈值是否靠谱
- `provider rerank` 是否有切默认的收益

**主要工作**

- 沉淀一份真实业务 query 样本集
- 为每条样本标注查询类型、预期命中文档/证据特征、是否更依赖 lexical
- 对比 fixed fallback、dynamic weighting、provider rerank 的收益
- 记录误判样本，形成下一轮调参依据

**样本建议覆盖**

- 设备名
- 料号
- 报警码
- 工序名
- SOP 编号
- 自然语言故障描述
- 混合问句
- 带 `document_id` 的单文档检索样本

**建议规模**

- 首轮至少 `30~50` 条 query

**产出物**

- 一份样本清单
- 一份首轮校准结论
- 一份建议参数调整表

**涉及文件**

- 建议新增：`docs/retrieval_query_samples.md`
- 可能补充：`backend/tests/test_hybrid_query_router_samples.py`
- 可能补充：`backend/tests/test_retrieval_chat.py`

**验收标准**

- 样本集可复用，不是一次性口头结论
- 能明确指出哪类 query 从 hybrid 中收益最大
- 能明确指出 mixed query 的误判点
- 能给出“是否灰度开启 dynamic weighting”和“是否推进 provider 默认”的判断依据

**明确不做**

- 不追求一次就把所有 query 分类规则调到完美
- 不提前上模型分类

---

### Issue 4

**标题**

`feat(observability): 统一检索解释字段到 retrieval/chat/snapshot/SOP`

**目标**

把当前已存在但分布不完全一致的解释性字段统一起来，方便排障、回放和业务解释。

**背景**

当前以下字段已经在部分链路里存在：

- `retrieval_strategy`
- `source_scope`
- `vector_score`
- `lexical_score`
- `fused_score`
- `query_type`
- `vector_weight`
- `lexical_weight`

但它们还没有在所有需要解释的对象里完整对齐。尤其是 snapshot context 目前还缺 `source_scope`。

**主要工作**

- 对齐 retrieval result、chat citation、SOP citation、snapshot context 的字段口径
- 让 trace/snapshot/details 能统一解释当前 query 的权重决策
- 保证部门优先/全局补充来源能从结果和快照里被看出来

**涉及文件**

- `backend/app/schemas/retrieval.py`
- `backend/app/schemas/chat.py`
- `backend/app/schemas/sop_generation.py`
- `backend/app/schemas/request_snapshot.py`
- `backend/app/services/request_snapshot_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/tests/test_retrieval_chat.py`

**验收标准**

- retrieval、chat、SOP、snapshot 的解释字段语义一致
- snapshot context 能看见 `source_scope`
- trace/snapshot 能解释当前 query 的 `query_type / vector_weight / lexical_weight`
- 排障时能回答“为什么这条证据来自本部门或全局补充”

**明确不做**

- 不把这些字段都提升成用户前台默认展示字段
- 仍以诊断/治理为主，前台展示按需控制

---

### Issue 5

**标题**

`test(retrieval): 补齐双链路一致性与回归矩阵`

**目标**

把当前较强的单点测试补成“检索 -> rerank -> chat/SOP”双链路一致性的回归矩阵。

**背景**

当前测试已经覆盖：

- hybrid fusion
- dynamic weighting
- 日志与 trace/snapshot 基础可观测性
- `compare_rerank`
- provider 与 heuristic 的回退逻辑

但组合场景还不够系统，特别是：

- `document_id + department/global dual-route`
- lexical 分支失败回退
- provider rerank 失败回退
- chat 与 SOP 是否真的消费同一批证据

**主要工作**

- 补齐 retrieval 服务组合场景测试
- 补齐 chat 与 SOP 双链路一致性测试
- 补齐 canary sample 的回归测试
- 补齐 explainability 字段的跨链路断言

**建议覆盖矩阵**

- `document_id` 限定检索
- 部门优先 + 全局补充双路召回
- lexical 分支报错退回 `vector_only`
- provider rerank 失败退回 `heuristic`
- dynamic weighting 关闭与开启两种模式
- chat 与 SOP 共用同一批 fusion/rerank 后证据

**涉及文件**

- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_query_profile_service.py`
- `backend/tests/test_reranker_client.py`
- `backend/tests/test_sop_generation_service.py`

**验收标准**

- 关键组合场景都有自动化覆盖
- 回退路径可测且稳定
- chat 与 SOP 对同一 query 的证据来源语义一致
- canary sample 的生成和作用域过滤不回退

**明确不做**

- 不追求一次性补齐所有历史测试空白
- 只优先覆盖当前 backlog 真正依赖的主路径

---

## 5. 推荐本轮最小交付

如果当前只做一轮最值当的检索优化，建议最小交付范围是：

1. 完成 Issue 1
2. 完成 Issue 2
3. 完成 Issue 3 的首轮样本和结论

这三项做完，基本就能回答两个最关键的问题：

- `model rerank` 能不能切默认
- `dynamic weighting` 值不值得灰度开启

Issue 4 和 Issue 5 建议紧跟着补，这样后面进入 `memory / query rewrite / tokenizer-aware context budgeting` 时，检索底座不会再次失去可解释性。

---

## 6. 一句话结论

当前检索方向的正确节奏是：

**先验证，再收口可观测性和配置，再决定是否灰度放量，最后才评估更高成本扩展。**

---

## 7. 老板看的一页版

### 当前处于什么阶段

当前系统的检索并不是“还没开始做”，而是已经有一套可运行的主链路：

- `hybrid retrieval` 已落地
- `department-first + global fallback` 已落地
- `model rerank provider + heuristic fallback` 已落地
- chat 与 SOP 已共享同一套检索与重排底座

现在的问题不在“有没有能力”，而在“能力是否已经收口到可上线、可解释、可回滚”。

### 为什么现在该做检索优化

因为接下来的 `memory / query rewrite / tokenizer-aware context budgeting / WeCom` 都会继续叠在现有检索链路上。

如果当前不先把检索底座收口，后面会出现这些问题：

- 排序效果变好还是变坏说不清
- provider 失败时回退语义不稳定
- 动态权重是否值得开启没有证据
- chat 与 SOP 链路解释口径不一致
- 后续加功能会把问题放大，而不是解决

### 本轮最值当的目标

本轮最值当的不是“换检索架构”，而是把当前已有能力收口成正式能力：

1. 明确 `rerank` 默认路由与回滚策略
2. 把 `dynamic weighting` 变成可配置、可灰度能力
3. 用真实业务 query 样本做首轮校准

### 本轮完成后能回答什么问题

- `model rerank` 能不能切成默认主路径
- `dynamic weighting` 值不值得灰度开启
- 哪类 query 从 hybrid 检索里收益最大
- provider 不稳定时系统会不会自动安全回退

### 本轮明确不做什么

- 不换向量库
- 不引入新检索集群
- 不重做 chunk 规则
- 不提前做复杂 query rewrite 编排
- 不做大规模检索架构重构

### 一句话汇报口径

当前这轮检索工作不是“做新系统”，而是把已落地的检索能力从“功能可用”推进到“生产可用”。

---

## 8. Issue 1 开发任务清单

### 目标

把 `Model Rerank` 从“代码里已经能跑的候选能力”，收口成“默认策略明确、失败可回退、日志可解释、可安全灰度”的正式在线能力。

### 交付边界

这轮只处理在线链路：

- `retrieval -> rerank -> llm`

不处理：

- 异步入库
- embedding 重算
- chunk 重切
- 新 provider 体系设计

### 涉及文件

- `backend/app/rag/rerankers/client.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/services/rerank_canary_service.py`
- `backend/tests/test_reranker_client.py`
- `backend/tests/test_query_profile_service.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_sop_generation_service.py`

### 建议拆分任务

#### Task 1. 收口 rerank 运行态语义

目标：

- 明确 `provider / heuristic / failed` 的运行态口径
- 明确 `default_strategy` 与 `effective_strategy` 的关系
- 明确冷却锁的生效条件与诊断字段

具体动作：

- 统一 `RerankerClient.get_runtime_status()` 的状态输出语义
- 校对 `ready / lock_active / lock_source / cooldown_remaining_seconds / detail`
- 明确探活失败、请求失败、超时、`429` 的 detail 文案

完成定义：

- 任意时刻都能根据运行态字段判断“当前实际走的是什么策略”

#### Task 2. 收口统一回退路径

目标：

- 让 provider 失败时的回退逻辑只走一条统一路径

具体动作：

- 校对 `QueryProfileService.rerank_with_fallback()` 的兜底语义
- 明确什么情况下允许直接抛错，什么情况下必须回退 `heuristic`
- 确保 chat 与 SOP 不各自再写一套 provider 异常处理

完成定义：

- provider 失败时，chat 与 SOP 拿到的 `rerank_strategy` 都稳定为 `heuristic`

#### Task 3. 收口 compare 与 canary 推荐逻辑

目标：

- 让 `compare_rerank` 真正成为“是否切默认”的决策依据

具体动作：

- 校对 `configured / heuristic / provider_candidate` 三路结果的语义
- 校对 `recommendation.decision` 的触发条件
- 明确 `eligible / hold / provider_active / rollback_active / not_applicable`
- 确保 compare 结果能稳定落盘到 canary sample

完成定义：

- 能根据连续 compare 样本判断是否值得把 `default_strategy` 从 `heuristic` 切到 `provider`

#### Task 4. 对齐 chat / SOP 日志与快照语义

目标：

- 保证业务链路对 rerank 的解释一致

具体动作：

- 校对 chat 日志里的 `rerank_strategy / rerank_provider / rerank_model`
- 校对 SOP 日志里的同名字段
- 校对 trace / snapshot / event log 的口径
- 确保 provider 成功、provider 失败回退、固定 heuristic 三种情形解释一致

完成定义：

- chat 与 SOP 在相同运行态下给出一致的 rerank 解释字段

#### Task 5. 补齐回归测试

目标：

- 用自动化测试把这轮收口固定下来

具体动作：

- 补 provider 成功路径测试
- 补 provider 超时测试
- 补 provider `429` 测试
- 补 provider 不可用后进入冷却锁测试
- 补 `default_strategy=heuristic` 时 provider 已就绪但不走默认路径测试
- 补 chat / SOP 双链路一致性测试

完成定义：

- 不同 rerank 运行态都有稳定回归测试覆盖

### 建议开发顺序

1. 先做 `Task 1 运行态语义`
2. 再做 `Task 2 统一回退路径`
3. 然后做 `Task 3 compare 与 canary 推荐逻辑`
4. 再做 `Task 4 chat / SOP 日志对齐`
5. 最后做 `Task 5 回归测试`

### 建议测试点

- provider 正常且 `default_strategy=provider`
- provider 正常但 `default_strategy=heuristic`
- provider health probe 失败
- provider request timeout
- provider 返回 `429`
- provider 连续失败后进入 cooldown lock
- cooldown 窗口内 compare 仍能解释当前回退原因
- chat 与 SOP 在同一状态下的 `rerank_strategy` 一致

### 验收标准

- 默认路由与实际路由的关系清晰、稳定、可解释
- provider 失败时主流程不中断，自动回退 `heuristic`
- `compare_rerank` 可作为切默认的真实决策依据
- canary sample 能持续沉淀对比样本
- chat 与 SOP 对 rerank 的日志和快照口径一致

### 完成后的直接收益

- 可以安全评估是否把 provider 提升为默认主路径
- 可以在不改异步入库的前提下提升在线证据排序质量
- 可以把后续 `memory / query rewrite` 建在更稳定的检索底座之上

---

## 9. Issue 2 开发任务清单

### 目标

把 `Dynamic Weighting` 从当前主要依赖 `Settings/.env` 的静态能力，收口成“可配置、可校验、可灰度、可回退”的系统配置能力。

### 交付边界

这轮只处理配置真源与运行时读取方式：

- `dynamic weighting enabled`
- `fixed/exact/semantic/mixed` 权重
- query 分类阈值

不处理：

- 模型分类
- 前台高级检索实验开关
- 更复杂的 query intent 编排

### 涉及文件

- `backend/app/core/config.py`
- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/system_config_service.py`
- `backend/app/schemas/system_config.py`
- `backend/tests/test_system_config_service.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_retrieval_query_router.py`
- `backend/tests/test_hybrid_query_router_samples.py`

### 建议拆分任务

#### Task 1. 定义 dynamic weighting 系统配置模型

目标：

- 把当前散在配置项里的权重与阈值抽成一组正式配置对象

具体动作：

- 在 `system_config` schema 里新增 dynamic weighting 配置结构
- 至少覆盖 `enabled`、`fixed/exact/semantic/mixed` 权重、`exact/semantic` 阈值
- 明确默认值与 `Settings` 默认值的映射关系

完成定义：

- dynamic weighting 的运行参数不再只能从 `.env` 口径理解

#### Task 2. 接入 SystemConfigService 读写与校验

目标：

- 让 dynamic weighting 配置成为系统配置真源的一部分

具体动作：

- 在 `SystemConfigService` 中加入默认配置构建
- 增加合法性校验
- 明确权重范围、阈值范围、关闭时的固定回退逻辑
- 保证旧配置文件缺字段时可平滑回退默认值

完成定义：

- 运行态读取的 dynamic weighting 参数来自系统配置真源，而不是只依赖启动时环境变量

#### Task 3. 收口 RetrievalQueryRouter 的参数来源

目标：

- 让 query 分类与分支权重统一从系统配置读取

具体动作：

- 调整 `RetrievalQueryRouter` 读取配置的方式
- 确保 `classify()` 和 `resolve_branch_weights()` 使用统一配置来源
- 保留 dynamic weighting 关闭时的 fixed fallback

完成定义：

- 开关、权重、阈值切换后，router 行为能随系统配置稳定变化

#### Task 4. 明确灰度与回退口径

目标：

- 给后续真实样本校准和试点放量留出安全开关

具体动作：

- 明确默认关闭
- 明确灰度开启后的回退方式
- 明确当 dynamic weighting 收益不稳定时如何一键退回 fixed fallback

完成定义：

- 无需改代码即可把 dynamic weighting 切回稳态基线

#### Task 5. 补齐配置与行为测试

目标：

- 用测试把系统配置收口固定下来

具体动作：

- 补配置 schema 与 service 测试
- 补 router 在不同配置下的行为测试
- 补 retrieval 服务命中 `exact / semantic / mixed` 的测试
- 补 dynamic weighting 关闭时回退 fixed fallback 的测试

完成定义：

- 配置变更不会悄悄打坏现有 hybrid 基线

### 建议开发顺序

1. 先做 `Task 1 配置模型`
2. 再做 `Task 2 Service 读写与校验`
3. 然后做 `Task 3 Router 参数来源收口`
4. 再做 `Task 4 灰度与回退口径`
5. 最后做 `Task 5 测试补齐`

### 建议测试点

- 默认配置缺省时仍保持关闭
- 非法权重被拦截
- 非法阈值被拦截
- `exact / semantic / mixed` 三类 query 都能命中对应权重
- dynamic weighting 关闭时回退 fixed fallback
- 配置热更新后 router 读取的新值生效

### 验收标准

- dynamic weighting 参数由系统配置统一管理
- 默认仍关闭，不破坏当前排序基线
- 开启后可观测，可解释，可回退
- 不需要改 `.env` 或重启才能完成常规调参

### 完成后的直接收益

- 后续做真实 query 样本校准时效率更高
- 可以先小范围灰度，而不是一次性全量打开
- 让 dynamic weighting 从“实验代码”进入“可治理能力”

---

## 10. Issue 3 开发任务清单

### 目标

建立一份可复用的真实业务 `query` 样本集，并基于样本完成首轮 hybrid/rerank 校准，给后续是否灰度放量提供决策依据。

### 交付边界

这轮主要做“样本、评估、结论”三件事：

- 样本沉淀
- 对比验证
- 参数建议

不处理：

- 大规模自动评测平台
- 模型级 query 分类
- 多轮 rewrite 联动评测

### 涉及文件

- 建议新增：`docs/retrieval_query_samples.md`
- 建议新增：`docs/retrieval_calibration_notes.md`
- `backend/tests/test_hybrid_query_router_samples.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_retrieval_query_router.py`
- 如有需要可补脚本：`scripts/`

### 建议拆分任务

#### Task 1. 沉淀首轮 query 样本集

目标：

- 把零散经验问题收成可重复使用的样本资产

具体动作：

- 汇总设备名、料号、报警码、工序名、SOP 编号、自然语言问句、混合问句
- 为每条 query 标注类别和预期命中说明
- 记录是否带 `document_id`、是否偏 lexical、是否偏 semantic

完成定义：

- 至少有一份结构化样本清单，而不是散落在聊天记录里

#### Task 2. 建立最小评估口径

目标：

- 用一致标准比较 fixed fallback、dynamic weighting、provider rerank

具体动作：

- 明确每条样本看什么
- 至少评估 top1、top3、是否命中期望证据、是否命中本部门优先结果
- 对 mixed query 记录误判情况

完成定义：

- 每条样本都能得到一份可比较结果，而不是只凭主观印象判断

#### Task 3. 做首轮规则阈值和权重校准

目标：

- 根据真实样本调整 exact/semantic/mixed 的阈值与权重

具体动作：

- 对比当前默认值与调整后的结果差异
- 重点看设备名、料号、报警码一类 exact query
- 重点看自然语言故障问句一类 semantic query
- 重点看 mixed query 的误判率是否可接受

完成定义：

- 能给出“先保持当前值”还是“建议调整到新值”的明确结论

#### Task 4. 做 provider rerank 收益验证

目标：

- 判断 model rerank 是否真的值得切默认

具体动作：

- 在同一批候选上比较 `heuristic` 与 `provider`
- 记录 top1 是否变化、topN 是否更贴近预期
- 汇总明显收益样本和无收益样本

完成定义：

- 能回答“provider rerank 有没有稳定收益”

#### Task 5. 输出首轮校准结论

目标：

- 把样本结果变成后续排期与上线决策材料

具体动作：

- 产出一份校准笔记
- 明确是否建议灰度开启 dynamic weighting
- 明确是否建议推进 provider 默认路由
- 列出下一轮需要补的误判样本

完成定义：

- 后续团队可以直接根据结论推进 Issue 1/2，而不是重新讨论一次

### 建议开发顺序

1. 先做 `Task 1 样本集`
2. 再做 `Task 2 评估口径`
3. 然后做 `Task 3 阈值与权重校准`
4. 再做 `Task 4 provider 收益验证`
5. 最后做 `Task 5 结论沉淀`

### 建议测试点

- exact query 是否优于当前 vector-only 基线
- semantic query 是否保持现有语义召回优势
- mixed query 是否出现明显误判
- 本部门优先结果是否仍然排在前面
- `document_id` 限定下是否仍不串文档

### 验收标准

- 至少沉淀一份 `30~50` 条的样本集
- 有一份可复用的校准结论
- 能明确指出 dynamic weighting 是否值得灰度开启
- 能明确指出 provider rerank 是否值得推进默认

### 完成后的直接收益

- 调参不再只凭感觉
- 后续检索优化有共同 benchmark
- 是否推进 provider 和 dynamic weighting 有真实依据

---

## 11. Issue 4 开发任务清单

### 目标

统一检索解释字段在 `retrieval / chat / SOP / request snapshot / trace` 中的契约，确保同一条证据在不同链路里能被一致解释。

### 交付边界

这轮只处理解释性字段对齐：

- `retrieval_strategy`
- `source_scope`
- `vector_score`
- `lexical_score`
- `fused_score`
- `query_type`
- `vector_weight`
- `lexical_weight`

不处理：

- 大规模前台展示改版
- 新的可视化报表
- 非主链路历史数据迁移

### 涉及文件

- `backend/app/schemas/retrieval.py`
- `backend/app/schemas/chat.py`
- `backend/app/schemas/sop_generation.py`
- `backend/app/schemas/request_snapshot.py`
- `backend/app/schemas/request_trace.py`
- `backend/app/services/request_snapshot_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_request_snapshot_service.py`

### 建议拆分任务

#### Task 1. 冻结解释字段口径

目标：

- 先明确哪些字段属于主契约，哪些属于诊断字段

具体动作：

- 梳理 retrieval result、chat citation、SOP citation、snapshot context、trace details 的字段
- 明确字段命名和语义
- 明确哪些字段允许为空、哪些字段在 hybrid 下必须存在

完成定义：

- 不同对象上的同名字段语义一致

#### Task 2. 补齐 snapshot context 缺失字段

目标：

- 让快照成为真正可回放、可解释的诊断对象

具体动作：

- 为 `RequestSnapshotContext` 增补缺失的解释字段
- 优先补 `source_scope`
- 确保 chat 与 SOP 两条构建路径都透传一致字段

完成定义：

- 从 snapshot 就能解释证据为什么来自本部门或全局补充

#### Task 3. 对齐 trace/snapshot/details 中的 query 决策信息

目标：

- 让动态权重决策能跨链路解释

具体动作：

- 对齐 `query_type / vector_weight / lexical_weight / dynamic_weighting_enabled`
- 确保 retrieval stage details、snapshot details、调试信息字段一致
- 必要时补 exact/semantic signals

完成定义：

- 同一请求在 trace 和 snapshot 里都能看到一致的权重决策

#### Task 4. 对齐 chat/SOP 引用构建逻辑

目标：

- 保证 chat 与 SOP 使用同一套证据解释口径

具体动作：

- 校对引用对象的字段透传
- 校对 document preview / degraded path / normal retrieval path
- 确保 fallback 情况下也不打乱字段语义

完成定义：

- chat 与 SOP 在正常和降级场景下都保持字段口径一致

#### Task 5. 补齐契约回归测试

目标：

- 用自动化测试把解释性契约固定下来

具体动作：

- 补 retrieval -> chat 的字段传递测试
- 补 retrieval -> SOP 的字段传递测试
- 补 snapshot context 的字段测试
- 补 trace/snapshot/details 的一致性测试

完成定义：

- 后续改链路时，不会悄悄打坏解释字段

### 建议开发顺序

1. 先做 `Task 1 字段口径冻结`
2. 再做 `Task 2 snapshot context 补齐`
3. 然后做 `Task 3 trace/snapshot 决策信息对齐`
4. 再做 `Task 4 chat/SOP 引用逻辑对齐`
5. 最后做 `Task 5 回归测试`

### 建议测试点

- hybrid 命中结果是否带 `retrieval_strategy`
- 部门优先双路召回结果是否带 `source_scope`
- chat citation 是否保留 `source_scope / fused_score`
- SOP citation 是否保留同一批字段
- snapshot context 是否与 citation 口径一致
- trace 与 snapshot 是否都能解释当前 query 权重

### 验收标准

- 检索解释字段在 retrieval/chat/SOP/snapshot 中一致
- snapshot 能解释来源范围与排序依据
- trace 与 snapshot 中的动态权重决策信息一致
- 降级路径不会打坏字段语义

### 完成后的直接收益

- 排障成本大幅下降
- 业务侧更容易理解“为什么是这条证据”
- 后续 memory、rewrite 接进来时不会丢失证据解释能力

---

## 12. Issue 5 开发任务清单

### 目标

把当前零散但基础不错的检索相关测试，补成“retrieval -> rerank -> chat/SOP”双链路一致性的回归矩阵。

### 交付边界

这轮以主路径组合测试为主：

- hybrid retrieval
- department/global dual-route
- rerank fallback
- chat/SOP 双链路一致性

不处理：

- 全量历史测试整理
- 压测平台
- 复杂性能基准体系

### 涉及文件

- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_query_profile_service.py`
- `backend/tests/test_reranker_client.py`
- `backend/tests/test_sop_generation_service.py`
- `backend/tests/test_request_snapshot_service.py`
- 如有必要可新增更细分的 retrieval regression 测试文件

### 建议拆分任务

#### Task 1. 补 retrieval 组合场景回归

目标：

- 先把 retrieval 服务层组合行为补稳

具体动作：

- 覆盖 `document_id + hybrid`
- 覆盖 `department/global dual-route`
- 覆盖 lexical 分支失败回退 `vector_only`
- 覆盖 dynamic weighting 开启/关闭

完成定义：

- retrieval 的主组合路径都有自动化测试兜底

#### Task 2. 补 rerank 回退矩阵

目标：

- 让 provider 与 heuristic 的回退组合行为可测

具体动作：

- 覆盖 provider 成功
- 覆盖 provider timeout
- 覆盖 provider `429`
- 覆盖 provider 不可用后进入 cooldown lock
- 覆盖 `default_strategy=heuristic` 但 provider 已就绪的场景

完成定义：

- rerank 运行态切换不会成为线上黑盒

#### Task 3. 补 chat/SOP 双链路一致性测试

目标：

- 确保两条上层业务链路消费统一检索证据

具体动作：

- 覆盖 chat 与 SOP 对同一批 retrieval results 的消费
- 覆盖两条链路的 `rerank_strategy` 一致性
- 覆盖 citation 字段一致性
- 覆盖降级场景下一致性

完成定义：

- chat 与 SOP 不会出现“一条证据两种说法”

#### Task 4. 补 explainability 与 snapshot 契约测试

目标：

- 让解释性字段成为有回归保护的正式契约

具体动作：

- 补 `source_scope / fused_score / retrieval_strategy` 的透传测试
- 补 snapshot context 与 citation 一致性测试
- 补 trace/snapshot 中 `query_type / vector_weight / lexical_weight` 的断言

完成定义：

- 后续链路改动不容易打坏诊断字段

#### Task 5. 收口最小回归执行清单

目标：

- 让这批测试能形成最小可执行回归清单

具体动作：

- 明确本轮核心测试文件
- 明确建议执行顺序
- 如有必要补一个最小回归说明文档

完成定义：

- 每次修改 retrieval/rerank 主链路后，都能快速跑一遍关键回归

### 建议开发顺序

1. 先做 `Task 1 retrieval 组合回归`
2. 再做 `Task 2 rerank 回退矩阵`
3. 然后做 `Task 3 chat/SOP 一致性`
4. 再做 `Task 4 explainability 与 snapshot 契约测试`
5. 最后做 `Task 5 最小回归执行清单`

### 建议测试点

- `document_id` 限定下不串文档
- 双路召回时本部门优先、全局补充
- lexical 分支失败后系统退回 `vector_only`
- provider 失败后系统退回 `heuristic`
- chat 与 SOP 的 citation 字段一致
- snapshot 与 citation 的 `source_scope / fused_score` 一致

### 验收标准

- 关键组合路径都有自动化测试覆盖
- 回退场景可测、稳定、可解释
- chat 与 SOP 双链路一致性可验证
- explainability 契约有回归保护

### 完成后的直接收益

- 改 retrieval/rerank 时更敢动代码
- 上线前能更快确认主链路没回退
- 后续继续做 memory、rewrite 时能复用这套回归底座

---

## 13. 建议排期与并行方式

### 总原则

这 5 个 issue 不是完全串行，也不是适合一股脑并行。

更合适的方式是：

- 先收口会影响运行语义和配置真源的部分
- 再用真实样本做校准
- 再补解释性与回归矩阵

一句话：

**先定路由和配置，再做样本校准，最后补契约和回归。**

---

### 建议先后顺序

推荐主顺序：

1. `Issue 1` 收口 `Model Rerank` 默认路由与回滚策略
2. `Issue 2` 收口 `Dynamic Weighting` 到系统配置真源
3. `Issue 3` 建真实 query 样本集并完成首轮校准
4. `Issue 4` 统一检索解释字段契约
5. `Issue 5` 补齐双链路一致性与回归矩阵

原因：

- `Issue 1` 会影响后面“provider 是否值得切默认”的判断口径
- `Issue 2` 会影响后面调权重和灰度的方式
- `Issue 3` 依赖前两项至少把运行语义和配置入口稳定下来
- `Issue 4` 最适合在样本校准之后做，因为那时更清楚哪些解释字段真正有价值
- `Issue 5` 最适合最后做，用来把前面四项成果固化

---

### 最合理的两阶段排法

#### 阶段 A：底座收口

包含：

- `Issue 1`
- `Issue 2`

阶段目标：

- 把 rerank 与 dynamic weighting 从“功能存在”推进到“运行语义明确、配置来源统一”

阶段完成标志：

- provider/heuristic 的运行态与回退语义清晰
- dynamic weighting 的开关、阈值、权重可从系统配置统一管理

#### 阶段 B：验证与固化

包含：

- `Issue 3`
- `Issue 4`
- `Issue 5`

阶段目标：

- 用真实样本验证收益
- 把解释性契约固定下来
- 把关键组合路径补进回归测试

阶段完成标志：

- 能回答“要不要切 provider 默认”“要不要灰度 dynamic weighting”
- 主链路有可解释性和回归保护

---

### 哪些可以并行

#### 可并行组合 1

- `Issue 1`
- `Issue 2`

为什么可以并行：

- `Issue 1` 主要围绕 rerank 路由、fallback、canary
- `Issue 2` 主要围绕 dynamic weighting 配置真源
- 两者都在 retrieval 相关域内，但关注点不同

并行时要注意：

- 两边都可能碰 `SystemConfigService`
- 需要提前约定配置模型边界，避免互相覆盖

建议拆法：

- 一人负责 `rerank` 运行态、compare、fallback
- 一人负责 dynamic weighting 配置 schema、service 校验、router 读取

#### 可并行组合 2

- `Issue 3`
- `Issue 4`

为什么可以并行：

- `Issue 3` 以样本、评估、校准为主
- `Issue 4` 以字段契约和解释性收口为主
- 样本结论会帮助 Issue 4 聚焦重点字段，但不阻塞其大部分实现

并行时要注意：

- 如果样本校准发现某些字段没有价值，Issue 4 不要过度扩字段

建议拆法：

- 一人负责样本清单、评估记录、参数建议
- 一人负责 snapshot/citation/trace 字段对齐

#### 可并行组合 3

- `Issue 4`
- `Issue 5`

为什么“部分可以并行”：

- `Issue 5` 可以先补已有主路径组合回归
- `Issue 4` 在补字段契约时，测试同学可以先写一部分失败用例

并行时要注意：

- 测试断言必须跟最终字段契约同步
- 不要一边改字段名，一边写死旧断言

---

### 哪些不建议并行

#### 不建议并行 1

- `Issue 1`
- `Issue 3`

原因：

- `Issue 3` 需要基于稳定的 rerank 运行语义做收益判断
- 如果 `Issue 1` 还在变化，样本评估结果会反复失真

#### 不建议并行 2

- `Issue 2`
- `Issue 3` 的参数结论部分

原因：

- `Issue 3` 会产出参数建议
- `Issue 2` 会定义这些参数怎么进入系统配置
- 如果同时推进且接口未定，最后要返工一次

#### 不建议并行 3

- `Issue 5`
- 所有上游 issue 一起全量并行

原因：

- 回归矩阵最怕主契约尚未冻结
- 如果边开发边大面积补测试，测试改动会被上游反复打散

---

### 如果只有 1 个人

建议顺序：

1. 先做 `Issue 1`
2. 再做 `Issue 2`
3. 再做 `Issue 3`
4. 然后做 `Issue 4`
5. 最后做 `Issue 5`

原因：

- 单人推进时最重要的是减少返工
- 这条顺序能保证“运行语义 -> 配置入口 -> 样本结论 -> 契约 -> 测试”逐层收口

---

### 如果有 2 个人

推荐排法：

第 1 波：

- A 负责 `Issue 1`
- B 负责 `Issue 2`

第 2 波：

- A 负责 `Issue 3`
- B 负责 `Issue 4`

第 3 波：

- A/B 一起收尾 `Issue 5`

原因：

- 前两波能最大化减少等待
- 第三波回归矩阵需要吸收前面两波结果，适合最后一起收口

---

### 如果有 3 个人

推荐排法：

第 1 波：

- A 负责 `Issue 1`
- B 负责 `Issue 2`
- C 预热 `Issue 5` 的基础回归清单与现有测试梳理

第 2 波：

- A 转 `Issue 3`
- B 转 `Issue 4`
- C 开始补 `Issue 5` 的稳定部分

第 3 波：

- 三人一起收尾 `Issue 5` 和遗留细节

注意：

- 第 1 波里 C 不建议大规模补测试代码，只建议先梳理现有用例、列回归矩阵、准备测试骨架

---

### 推荐里程碑

#### 里程碑 1

`Retrieval Runtime Hardened`

完成条件：

- `Issue 1` 完成
- `Issue 2` 完成

可回答的问题：

- rerank 默认怎么跑
- dynamic weighting 参数从哪里配

#### 里程碑 2

`Retrieval Quality Calibrated`

完成条件：

- `Issue 3` 完成

可回答的问题：

- 是否灰度开启 dynamic weighting
- 是否推进 provider 默认

#### 里程碑 3

`Retrieval Contract Hardened`

完成条件：

- `Issue 4`
- `Issue 5`

可回答的问题：

- 检索证据为什么这样排序
- 改 retrieval/rerank 之后怎么快速确认没回退

---

### 最终建议

如果你现在就要开始排开发，我建议直接按这个方式落：

1. 先立项 `Issue 1` 和 `Issue 2`
2. 等两者接口和配置边界稳定后，再开 `Issue 3`
3. `Issue 4` 和 `Issue 5` 作为第二阶段收口项跟进

这是当前这套仓库里返工最少、收益最高、也最符合现状的一种排法。
